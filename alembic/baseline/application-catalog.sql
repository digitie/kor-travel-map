-- `0236 → 300` handoff와 fresh `300` baseline이 함께 쓰는 불변 application
-- catalog receipt. 각 행은 `kind`, `schema_name`, `object_name`, `definition`의
-- 결정론적 표현이며, 호출자는 UTF-8 행 + LF를 SHA-256 한다.
--
-- 이 파일은 `scripts/run-admin-feature-clone-live-acceptance.sh`의 schema/database/
-- extension receipt와 같은 catalog 축을 한 query로 묶는다. `300` handoff는 raw
-- `alembic_version`만 stamp할 수 있으므로, source와 destination 모두 이 receipt가
-- immutable reference hash와 같아야 한다.
WITH extension_member AS (
    -- extension header/version만으로는 member function body·ACL, operator family, config
    -- relation을 ALTER한 drift를 볼 수 없다. 아래 receipt branch들이 이 immutable member
    -- inventory를 definition/data까지 다시 읽는다.
    SELECT
        dependency.classid,
        dependency.objid,
        extension.extname AS extension_name,
        extension_namespace.nspname AS extension_schema
    FROM pg_catalog.pg_depend AS dependency
    JOIN pg_catalog.pg_extension AS extension
      ON extension.oid = dependency.refobjid
    JOIN pg_catalog.pg_namespace AS extension_namespace
      ON extension_namespace.oid = extension.extnamespace
    WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
      AND dependency.deptype = 'e'
      AND dependency.objsubid = 0
), role_class AS (
    -- extension을 만든 bootstrap superuser의 실제 role 이름은 Compose의
    -- `POSTGRES_USER`에 따라 바뀐다. 그 이름을 receipt에 고정하지 않되,
    -- application role 또는 일반 role로 소유권을 옮긴 drift는 반드시 다른 값이
    -- 되게 한다. fresh/handoff의 별도 role guard도 이 분류를 다시 검증한다.
    SELECT
        role.oid,
        CASE
            -- application처럼 보이는 role이 실수로 SUPERUSER를 받아도 bootstrap
            -- class로 숨기지 않는다. fresh/handoff guard와 별개로 receipt도 이
            -- 소유권 drift를 fail-close해야 한다.
            WHEN role.rolname LIKE 'ktm\_%' ESCAPE '\' THEN role.rolname
            WHEN role.rolsuper THEN '<bootstrap-superuser>'
            ELSE '<non-superuser:' || role.rolname || '>'
        END AS canonical_name
    FROM pg_catalog.pg_roles AS role
), objects AS (
    SELECT
        'column'::text AS kind,
        namespace.nspname AS schema_name,
        relation.relname AS object_name,
        row_number() OVER (
            PARTITION BY attribute.attrelid ORDER BY attribute.attnum
        )::text || ':' || attribute.attname || ':' ||
        pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) || ':' ||
        attribute.attnotnull::text || ':' ||
        attribute.attidentity::text || ':' ||
        attribute.attgenerated::text || ':' ||
        attribute.attndims::text || ':' ||
        attribute.atthasdef::text || ':' ||
        attribute.attislocal::text || ':' ||
        attribute.attinhcount::text || ':' ||
        CASE
            WHEN attribute.attcollation = 0 THEN ''
            ELSE attribute.attcollation::regcollation::text
        END || ':' ||
        COALESCE(attribute.attacl::text, '') || ':' ||
        COALESCE(pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid), '') || ':' ||
        attribute.attstattarget::text || ':' ||
        COALESCE(
            (SELECT string_agg(option, ',' ORDER BY option)
             FROM unnest(attribute.attoptions) AS option),
            ''
        ) || ':' ||
        COALESCE(
            (SELECT string_agg(option, ',' ORDER BY option)
             FROM unnest(attribute.attfdwoptions) AS option),
            ''
        ) || ':' ||
        attribute.attstorage::text || ':' ||
        COALESCE(attribute.attcompression::text, '')
            AS definition
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef AS default_row
      ON default_row.adrelid = attribute.attrelid
     AND default_row.adnum = attribute.attnum
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    UNION ALL
    -- Logical column numbering excludes dropped attributes.  PostgreSQL keeps
    -- those physical slots, however, and a raw `0236` relation that did
    -- ADD COLUMN then DROP COLUMN cannot be reproduced by a fresh root merely
    -- because its visible columns match.  Receipt every positive slot
    -- separately so that this historical layout cannot cross the boundary.
    SELECT
        'relation_attribute_slot',
        namespace.nspname,
        relation.relname,
        attribute.attnum::text || ':' || attribute.attisdropped::text || ':' ||
        CASE
            WHEN attribute.attisdropped THEN '<dropped>'
            ELSE pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
        END
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND attribute.attnum > 0
    UNION ALL
    -- `CREATE TYPE ... AS (...)`는 pg_class.relkind='c'이고 ordinary table column
    -- branch에는 나오지 않는다. composite member의 type/collation/ACL/default를 별도
    -- receipt로 남겨 type layout 또는 attribute authority drift를 stamp 전에 막는다.
    SELECT
        'composite_attribute',
        namespace.nspname,
        relation.relname,
        attribute.attnum::text || ':' || attribute.attname || ':' ||
        pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) || ':' ||
        attribute.attnotnull::text || ':' ||
        CASE
            WHEN attribute.attcollation = 0 THEN ''
            ELSE attribute.attcollation::regcollation::text
        END || ':' ||
        COALESCE(attribute.attacl::text, '') || ':' ||
        COALESCE(pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid), '')
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef AS default_row
      ON default_row.adrelid = attribute.attrelid
     AND default_row.adnum = attribute.attnum
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind = 'c'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    UNION ALL
    SELECT
        'composite_attribute_slot',
        namespace.nspname,
        relation.relname,
        attribute.attnum::text || ':' || attribute.attisdropped::text || ':' ||
        CASE
            WHEN attribute.attisdropped THEN '<dropped>'
            ELSE pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
        END
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind = 'c'
      AND attribute.attnum > 0
    UNION ALL
    SELECT
        'relation', namespace.nspname, relation.relname,
        concat_ws(
            ':',
            relation.relkind,
            relation.relnatts,
            CASE WHEN relation.relam = 0 THEN '<none>'
                 ELSE COALESCE(access_method.amname, '<missing>') END,
            relation.relowner::regrole::text,
            COALESCE(
                (
                    SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                    FROM unnest(relation.relacl) AS entry
                    WHERE entry::text <> ALL (
                        SELECT default_entry::text
                        FROM unnest(
                            pg_catalog.acldefault(
                                CASE WHEN relation.relkind = 'S' THEN 's' ELSE 'r' END::"char",
                                relation.relowner
                            )
                        ) AS default_entry
                    )
                ),
                ''
            ),
            CASE
                WHEN relation.reltablespace = 0 THEN '<database-default>'
                ELSE COALESCE(tablespace.spcname, '<missing>')
            END,
            relation.relrowsecurity,
            relation.relforcerowsecurity,
            COALESCE(pg_catalog.pg_get_expr(relation.relpartbound, relation.oid, true), ''),
            relation.relpersistence,
            relation.relreplident,
            COALESCE(
                (SELECT string_agg(option, ',' ORDER BY option)
                 FROM unnest(relation.reloptions) AS option),
                ''
            ),
            COALESCE(
                (SELECT string_agg(option, ',' ORDER BY option)
                 FROM pg_catalog.pg_class AS toast_relation
                 CROSS JOIN LATERAL unnest(toast_relation.reloptions) AS option
                 WHERE toast_relation.oid = relation.reltoastrelid),
                ''
            ),
            COALESCE(
                (SELECT string_agg(index_relation.relname, ',' ORDER BY index_relation.relname)
                 FROM pg_catalog.pg_index AS index_link
                 JOIN pg_catalog.pg_class AS index_relation
                   ON index_relation.oid = index_link.indexrelid
                 WHERE index_link.indrelid = relation.oid
                   AND index_link.indisreplident),
                ''
            )
        )
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_am AS access_method ON access_method.oid = relation.relam
    LEFT JOIN pg_catalog.pg_tablespace AS tablespace
      ON tablespace.oid = relation.reltablespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    UNION ALL
    SELECT
        'composite_relation',
        namespace.nspname,
        relation.relname,
        concat_ws(
            ':',
            relation.relkind,
            relation.relnatts,
            relation.relowner::regrole::text,
            COALESCE(relation.relacl::text, ''),
            relation.relpersistence,
            COALESCE(
                (SELECT string_agg(option, ',' ORDER BY option)
                 FROM unnest(relation.reloptions) AS option),
                ''
            )
        )
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind = 'c'
    UNION ALL
    SELECT
        'constraint', namespace.nspname, relation.relname,
        concat_ws(
            ':',
            constraint_row.conname,
            constraint_row.contype,
            COALESCE(
                (
                    SELECT string_agg(
                        key_attribute.attname,
                        ',' ORDER BY array_position(constraint_row.conkey, key_attribute.attnum)
                    )
                    FROM pg_catalog.pg_attribute AS key_attribute
                    WHERE key_attribute.attrelid = constraint_row.conrelid
                      AND key_attribute.attnum = ANY(constraint_row.conkey)
                ),
                ''
            ),
            COALESCE(
                (
                    SELECT string_agg(
                        referenced_attribute.attname,
                        ',' ORDER BY array_position(
                            constraint_row.confkey,
                            referenced_attribute.attnum
                        )
                    )
                    FROM pg_catalog.pg_attribute AS referenced_attribute
                    WHERE referenced_attribute.attrelid = constraint_row.confrelid
                      AND referenced_attribute.attnum = ANY(constraint_row.confkey)
                ),
                ''
            ),
            COALESCE(constraint_row.confrelid::regclass::text, ''),
            constraint_row.confupdtype,
            constraint_row.confdeltype,
            constraint_row.confmatchtype,
            constraint_row.condeferrable,
            constraint_row.condeferred,
            constraint_row.convalidated,
            constraint_row.connoinherit,
            COALESCE(
                (
                    SELECT string_agg(
                        exclusion.operator_oid::regoperator::text,
                        ',' ORDER BY exclusion.ordinality
                    )
                    FROM unnest(constraint_row.conexclop::oid[]) WITH ORDINALITY
                      AS exclusion(operator_oid, ordinality)
                ),
                ''
            ),
            COALESCE(pg_catalog.pg_get_constraintdef(constraint_row.oid, true), '')
        )
    FROM pg_catalog.pg_constraint AS constraint_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_row.conrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'index', namespace.nspname, relation.relname,
        index_row.relname || ':' ||
        index_link.indisvalid::text || ':' ||
        index_link.indisready::text || ':' ||
        index_link.indislive::text || ':' ||
        index_link.indisreplident::text || ':' ||
        COALESCE(
            (SELECT string_agg(option, ',' ORDER BY option)
             FROM unnest(index_row.reloptions) AS option),
            ''
        ) || ':' ||
        pg_catalog.pg_get_indexdef(index_row.oid)
    FROM pg_catalog.pg_index AS index_link
    JOIN pg_catalog.pg_class AS relation ON relation.oid = index_link.indrelid
    JOIN pg_catalog.pg_class AS index_row ON index_row.oid = index_link.indexrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'trigger', namespace.nspname, relation.relname,
        trigger_row.tgname || ':' ||
        trigger_row.tgenabled::text || ':' ||
        pg_catalog.pg_get_triggerdef(trigger_row.oid, true)
    FROM pg_catalog.pg_trigger AS trigger_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_row.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND NOT trigger_row.tgisinternal
    UNION ALL
    SELECT
        'view', namespace.nspname, relation.relname,
        pg_catalog.pg_get_viewdef(relation.oid, true)
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('v', 'm')
    UNION ALL
    SELECT
        'routine',
        namespace.nspname,
        routine.proname || ':' || pg_catalog.pg_get_function_identity_arguments(routine.oid),
        routine.proowner::regrole::text || ':' ||
        COALESCE(
            (
                SELECT string_agg(
                    concat_ws(
                        '/',
                        CASE
                            WHEN privilege.grantee = 0 THEN 'public'
                            ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
                        END,
                        pg_catalog.pg_get_userbyid(privilege.grantor),
                        privilege.privilege_type,
                        privilege.is_grantable
                    ),
                    ',' ORDER BY
                        CASE
                            WHEN privilege.grantee = 0 THEN 'public'
                            ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
                        END,
                        pg_catalog.pg_get_userbyid(privilege.grantor),
                        privilege.privilege_type,
                        privilege.is_grantable
                )
                FROM aclexplode(
                    COALESCE(
                        routine.proacl,
                        pg_catalog.acldefault('f'::"char", routine.proowner)
                    )
                ) AS privilege
            ),
            ''
        ) || ':' || pg_catalog.pg_get_functiondef(routine.oid)
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'type',
        namespace.nspname,
        type_row.typname,
        concat_ws(
            ':',
            type_row.typtype,
            type_row.typcategory,
            type_row.typnotnull,
            type_row.typbasetype::regtype::text,
            CASE WHEN type_row.typelem = 0 THEN '' ELSE type_row.typelem::regtype::text END,
            CASE WHEN type_row.typarray = 0 THEN '' ELSE type_row.typarray::regtype::text END,
            type_row.typtypmod,
            type_row.typowner::regrole::text,
            COALESCE(type_row.typacl::text, ''),
            CASE
                WHEN type_row.typcollation = 0 THEN ''
                ELSE type_row.typcollation::regcollation::text
            END,
            COALESCE(
                pg_catalog.pg_get_expr(type_row.typdefaultbin, 0, true),
                type_row.typdefault,
                ''
            ),
            COALESCE(enum_values.labels, '')
        )
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = type_row.typnamespace
    LEFT JOIN LATERAL (
        SELECT string_agg(enum_row.enumlabel, ',' ORDER BY enum_row.enumsortorder)
          AS labels
        FROM pg_catalog.pg_enum AS enum_row
        WHERE enum_row.enumtypid = type_row.oid
    ) AS enum_values ON true
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND type_row.typrelid = 0
      AND type_row.typisdefined
    UNION ALL
    -- Table row type도 grantable PostgreSQL type이다. `GRANT USAGE ON TYPE
    -- feature.features TO PUBLIC`처럼 relation ACL과 별개의 typacl 변경은 ordinary
    -- relation/column receipt만으로 보이지 않으므로 all implicit row types를 포함한다.
    SELECT
        'row_type',
        namespace.nspname,
        type_row.typname,
        concat_ws(
            ':',
            relation.relkind,
            relation.relname,
            type_row.typtype,
            type_row.typcategory,
            type_row.typnotnull,
            type_row.typowner::regrole::text,
            COALESCE(type_row.typacl::text, ''),
            CASE
                WHEN type_row.typcollation = 0 THEN ''
                ELSE type_row.typcollation::regcollation::text
            END,
            COALESCE(
                pg_catalog.pg_get_expr(type_row.typdefaultbin, 0, true),
                type_row.typdefault,
                ''
            )
        )
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = type_row.typrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND type_row.typrelid <> 0
      AND type_row.typisdefined
    UNION ALL
    SELECT
        'range_type',
        namespace.nspname,
        type_row.typname,
        concat_ws(
            ':',
            range_row.rngsubtype::regtype::text,
            CASE WHEN range_row.rngcollation = 0 THEN ''
                 ELSE range_row.rngcollation::regcollation::text END,
            range_opclass_namespace.nspname || '.' || range_opclass.opcname || ':' ||
                range_access_method.amname,
            CASE WHEN range_row.rngcanonical = 0 THEN ''
                 ELSE range_row.rngcanonical::regprocedure::text END,
            CASE WHEN range_row.rngsubdiff = 0 THEN ''
                 ELSE range_row.rngsubdiff::regprocedure::text END,
            CASE WHEN range_row.rngmultitypid = 0 THEN ''
                 ELSE range_row.rngmultitypid::regtype::text END
        )
    FROM pg_catalog.pg_range AS range_row
    JOIN pg_catalog.pg_type AS type_row ON type_row.oid = range_row.rngtypid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    JOIN pg_catalog.pg_opclass AS range_opclass ON range_opclass.oid = range_row.rngsubopc
    JOIN pg_catalog.pg_namespace AS range_opclass_namespace
      ON range_opclass_namespace.oid = range_opclass.opcnamespace
    JOIN pg_catalog.pg_am AS range_access_method ON range_access_method.oid = range_opclass.opcmethod
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'domain_constraint',
        namespace.nspname,
        type_row.typname,
        concat_ws(
            ':',
            constraint_row.conname,
            constraint_row.contype,
            constraint_row.convalidated,
            constraint_row.connoinherit,
            COALESCE(pg_catalog.pg_get_constraintdef(constraint_row.oid, true), '')
        )
    FROM pg_catalog.pg_constraint AS constraint_row
    JOIN pg_catalog.pg_type AS type_row ON type_row.oid = constraint_row.contypid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'policy',
        namespace.nspname,
        relation.relname,
        policy.polname || ':' || policy.polcmd::text || ':' || policy.polpermissive::text || ':' ||
        COALESCE(
            (
                SELECT string_agg(
                    CASE
                        WHEN policy_role.role_oid = 0 THEN 'public'
                        ELSE pg_catalog.pg_get_userbyid(policy_role.role_oid)
                    END,
                    ',' ORDER BY
                        CASE
                            WHEN policy_role.role_oid = 0 THEN 'public'
                            ELSE pg_catalog.pg_get_userbyid(policy_role.role_oid)
                        END
                )
                FROM unnest(policy.polroles) AS policy_role(role_oid)
            ),
            ''
        ) || ':' ||
        COALESCE(pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true), '') || ':' ||
        COALESCE(pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true), '')
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'sequence',
        namespace.nspname,
        relation.relname,
        concat_ws(
            ':',
            sequence.seqstart,
            sequence.seqincrement,
            sequence.seqmax,
            sequence.seqmin,
            sequence.seqcache,
            sequence.seqcycle,
            sequence.seqtypid::regtype::text,
            COALESCE(
                (
                    SELECT string_agg(
                        owner_namespace.nspname || '.' || owner_relation.relname || '.' ||
                        COALESCE(owner_attribute.attname, '<whole-relation>') || ':' ||
                        dependency.deptype::text,
                        ',' ORDER BY owner_namespace.nspname, owner_relation.relname,
                                   COALESCE(owner_attribute.attname, '<whole-relation>'),
                                   dependency.deptype::text
                    )
                    FROM pg_catalog.pg_depend AS dependency
                    JOIN pg_catalog.pg_class AS owner_relation
                      ON owner_relation.oid = dependency.refobjid
                    JOIN pg_catalog.pg_namespace AS owner_namespace
                      ON owner_namespace.oid = owner_relation.relnamespace
                    LEFT JOIN pg_catalog.pg_attribute AS owner_attribute
                      ON owner_attribute.attrelid = dependency.refobjid
                     AND owner_attribute.attnum = dependency.refobjsubid
                    WHERE dependency.classid = 'pg_catalog.pg_class'::regclass
                      AND dependency.objid = sequence.seqrelid
                      AND dependency.refclassid = 'pg_catalog.pg_class'::regclass
                      AND dependency.deptype IN ('a', 'i')
                ),
                '<none>'
            )
        )
    FROM pg_catalog.pg_sequence AS sequence
    JOIN pg_catalog.pg_class AS relation ON relation.oid = sequence.seqrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'extended_statistics',
        statistics_namespace.nspname,
        statistics.stxname,
        concat_ws(
            ':',
            relation_namespace.nspname || '.' || relation.relname,
            statistics.stxowner::regrole::text,
            COALESCE(
                (SELECT string_agg(kind::text, ',' ORDER BY kind::text)
                 FROM unnest(statistics.stxkind) AS kind),
                ''
            ),
            COALESCE(
                (SELECT string_agg(attribute.attname, ',' ORDER BY key.ordinality)
                 FROM unnest(statistics.stxkeys::smallint[]) WITH ORDINALITY
                   AS key(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = statistics.stxrelid
                  AND attribute.attnum = key.attnum),
                ''
            ),
            statistics.stxstattarget::text,
            pg_catalog.pg_get_statisticsobjdef(statistics.oid)
        )
    FROM pg_catalog.pg_statistic_ext AS statistics
    JOIN pg_catalog.pg_namespace AS statistics_namespace
      ON statistics_namespace.oid = statistics.stxnamespace
    JOIN pg_catalog.pg_class AS relation ON relation.oid = statistics.stxrelid
    JOIN pg_catalog.pg_namespace AS relation_namespace
      ON relation_namespace.oid = relation.relnamespace
    WHERE statistics_namespace.nspname IN ('feature', 'ops', 'provider_sync')
       OR relation_namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    -- view의 내부 `_RETURN` rule은 이미 `view` 축이 pg_get_viewdef()로 canonical하게
    -- 담는다. 그 밖의 rule은 relation/trigger/routine 어디에도 나타나지 않아 DML 의미를
    -- 바꾼 채 handoff를 통과할 수 있으므로 별도 receipt 행으로 고정한다.
    SELECT
        'rule',
        namespace.nspname,
        relation.relname || ':' || rewrite_row.rulename,
        pg_catalog.pg_get_ruledef(rewrite_row.oid, true)
    FROM pg_catalog.pg_rewrite AS rewrite_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = rewrite_row.ev_class
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND rewrite_row.rulename <> '_RETURN'
    UNION ALL
    -- child → parent/순서가 같아야 partition attach와 일반 inheritance의 의미가 같다.
    -- relation.relpartbound만으로는 child가 어느 parent에 붙었는지 알 수 없다.
    SELECT
        'inheritance',
        child_namespace.nspname,
        child_relation.relname || ':' || parent_namespace.nspname || '.' || parent_relation.relname,
        inheritance.inhseqno::text
    FROM pg_catalog.pg_inherits AS inheritance
    JOIN pg_catalog.pg_class AS child_relation ON child_relation.oid = inheritance.inhrelid
    JOIN pg_catalog.pg_namespace AS child_namespace
      ON child_namespace.oid = child_relation.relnamespace
    JOIN pg_catalog.pg_class AS parent_relation ON parent_relation.oid = inheritance.inhparent
    JOIN pg_catalog.pg_namespace AS parent_namespace
      ON parent_namespace.oid = parent_relation.relnamespace
    WHERE child_namespace.nspname IN ('feature', 'ops', 'provider_sync')
       OR parent_namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'partitioned_table',
        namespace.nspname,
        relation.relname,
        concat_ws(
            ':',
            partitioned.partstrat,
            pg_catalog.pg_get_partkeydef(partitioned.partrelid),
            COALESCE(
                default_namespace.nspname || '.' || default_relation.relname,
                ''
            )
        )
    FROM pg_catalog.pg_partitioned_table AS partitioned
    JOIN pg_catalog.pg_class AS relation ON relation.oid = partitioned.partrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_class AS default_relation ON default_relation.oid = partitioned.partdefid
    LEFT JOIN pg_catalog.pg_namespace AS default_namespace
      ON default_namespace.oid = default_relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    -- FDW table/server option은 외부 source를 바꾸는 operational contract다. option
    -- plaintext(연결 문자열 포함 가능)는 receipt에 내보내지 않고 deterministic digest만
    -- 포함한다. 전체 catalog stream은 다시 SHA-256으로 고정된다.
    SELECT
        'foreign_table',
        namespace.nspname,
        relation.relname,
        concat_ws(
            ':',
            server.srvname,
            wrapper.fdwname,
            md5(COALESCE(array_to_string(foreign_table.ftoptions, chr(30)), ''))
        )
    FROM pg_catalog.pg_foreign_table AS foreign_table
    JOIN pg_catalog.pg_class AS relation ON relation.oid = foreign_table.ftrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_foreign_server AS server ON server.oid = foreign_table.ftserver
    JOIN pg_catalog.pg_foreign_data_wrapper AS wrapper ON wrapper.oid = server.srvfdw
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'foreign_server',
        '<cluster>',
        server.srvname,
        concat_ws(
            ':',
            server.srvowner::regrole::text,
            wrapper.fdwname,
            COALESCE(server.srvtype, ''),
            COALESCE(server.srvversion, ''),
            md5(COALESCE(array_to_string(wrapper.fdwoptions, chr(30)), '')),
            md5(COALESCE(array_to_string(server.srvoptions, chr(30)), '')),
            COALESCE(server.srvacl::text, '')
        )
    FROM pg_catalog.pg_foreign_server AS server
    JOIN pg_catalog.pg_foreign_data_wrapper AS wrapper ON wrapper.oid = server.srvfdw
    WHERE EXISTS (
        SELECT 1
        FROM pg_catalog.pg_foreign_table AS foreign_table
        JOIN pg_catalog.pg_class AS relation ON relation.oid = foreign_table.ftrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE foreign_table.ftserver = server.oid
          AND namespace.nspname IN ('feature', 'ops', 'provider_sync')
    )
    UNION ALL
    SELECT
        'publication',
        '<database>',
        publication.pubname,
        concat_ws(
            ':',
            publication.pubowner::regrole::text,
            publication.puballtables,
            publication.pubinsert,
            publication.pubupdate,
            publication.pubdelete,
            publication.pubtruncate,
            publication.pubviaroot
        )
    FROM pg_catalog.pg_publication AS publication
    UNION ALL
    SELECT
        'publication_relation',
        namespace.nspname,
        publication.pubname || ':' || relation.relname,
        ''
    FROM pg_catalog.pg_publication_rel AS publication_relation
    JOIN pg_catalog.pg_publication AS publication ON publication.oid = publication_relation.prpubid
    JOIN pg_catalog.pg_class AS relation ON relation.oid = publication_relation.prrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    -- The final source has no standalone app-schema semantic objects in these
    -- catalogs. They are nevertheless receipt rows rather than an implicit
    -- absence assumption: an injected text-search mapping, conversion,
    -- collation, operator, or operator class therefore changes the exact
    -- source receipt before a metadata-only handoff can stamp `300`.
    SELECT
        'application_semantic_collation',
        namespace.nspname,
        collation_row.collname,
        concat_ws(
            ':',
            collation_row.collowner::regrole::text,
            collation_row.collprovider,
            collation_row.collisdeterministic,
            collation_row.collencoding,
            COALESCE(collation_row.collcollate, ''),
            COALESCE(collation_row.collctype, ''),
            COALESCE(collation_row.colliculocale, ''),
            COALESCE(collation_row.collicurules, ''),
            COALESCE(collation_row.collversion, '')
        )
    FROM pg_catalog.pg_collation AS collation_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = collation_row.collnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_operator',
        namespace.nspname,
        operator_row.oid::regoperator::text,
        concat_ws(
            ':',
            operator_row.oprowner::regrole::text,
            operator_row.oprkind,
            operator_row.oprleft::regtype::text,
            operator_row.oprright::regtype::text,
            operator_row.oprresult::regtype::text,
            operator_row.oprcode::regprocedure::text,
            CASE WHEN operator_row.oprrest = 0 THEN '' ELSE operator_row.oprrest::regprocedure::text END,
            CASE WHEN operator_row.oprjoin = 0 THEN '' ELSE operator_row.oprjoin::regprocedure::text END,
            operator_row.oprcanmerge,
            operator_row.oprcanhash
        )
    FROM pg_catalog.pg_operator AS operator_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_row.oprnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_cast',
        source_namespace.nspname || '|' || target_namespace.nspname,
        cast_row.castsource::regtype::text || '->' || cast_row.casttarget::regtype::text,
        concat_ws(
            ':',
            cast_row.castcontext,
            cast_row.castmethod,
            CASE WHEN cast_row.castfunc = 0 THEN '' ELSE cast_row.castfunc::regprocedure::text END
        )
    FROM pg_catalog.pg_cast AS cast_row
    JOIN pg_catalog.pg_type AS source_type ON source_type.oid = cast_row.castsource
    JOIN pg_catalog.pg_type AS target_type ON target_type.oid = cast_row.casttarget
    JOIN pg_catalog.pg_namespace AS source_namespace ON source_namespace.oid = source_type.typnamespace
    JOIN pg_catalog.pg_namespace AS target_namespace ON target_namespace.oid = target_type.typnamespace
    WHERE source_namespace.nspname IN ('feature', 'ops', 'provider_sync')
       OR target_namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_opfamily',
        namespace.nspname,
        family.opfname,
        family.opfowner::regrole::text || ':' || access_method.amname
    FROM pg_catalog.pg_opfamily AS family
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = family.opfmethod
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_opclass',
        namespace.nspname,
        class.opcname,
        concat_ws(
            ':',
            class.opcowner::regrole::text,
            access_method.amname,
            family.opfname,
            class.opcintype::regtype::text,
            class.opcdefault,
            CASE WHEN class.opckeytype = 0 THEN '' ELSE class.opckeytype::regtype::text END
        )
    FROM pg_catalog.pg_opclass AS class
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = class.opcnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = class.opcmethod
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = class.opcfamily
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_conversion',
        namespace.nspname,
        conversion.conname,
        concat_ws(
            ':',
            conversion.conowner::regrole::text,
            conversion.conforencoding,
            conversion.contoencoding,
            conversion.conproc::regprocedure::text,
            conversion.condefault
        )
    FROM pg_catalog.pg_conversion AS conversion
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = conversion.connamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_ts_config',
        namespace.nspname,
        configuration.cfgname,
        configuration.cfgowner::regrole::text || ':' ||
        parser_namespace.nspname || '.' || parser.prsname
    FROM pg_catalog.pg_ts_config AS configuration
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
    JOIN pg_catalog.pg_ts_parser AS parser ON parser.oid = configuration.cfgparser
    JOIN pg_catalog.pg_namespace AS parser_namespace ON parser_namespace.oid = parser.prsnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_ts_config_map',
        namespace.nspname,
        configuration.cfgname || ':' || mapping.maptokentype::text || ':' || mapping.mapseqno::text,
        mapping.mapdict::regdictionary::text
    FROM pg_catalog.pg_ts_config_map AS mapping
    JOIN pg_catalog.pg_ts_config AS configuration ON configuration.oid = mapping.mapcfg
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_ts_dictionary',
        namespace.nspname,
        dictionary.dictname,
        concat_ws(
            ':',
            dictionary.dictowner::regrole::text,
            template_namespace.nspname || '.' || template.tmplname,
            COALESCE(dictionary.dictinitoption, '')
        )
    FROM pg_catalog.pg_ts_dict AS dictionary
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = dictionary.dictnamespace
    JOIN pg_catalog.pg_ts_template AS template ON template.oid = dictionary.dicttemplate
    JOIN pg_catalog.pg_namespace AS template_namespace ON template_namespace.oid = template.tmplnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_ts_parser',
        namespace.nspname,
        parser.prsname,
        concat_ws(
            ':',
            parser.prsstart::regprocedure::text,
            parser.prstoken::regprocedure::text,
            parser.prsend::regprocedure::text,
            parser.prsheadline::regprocedure::text,
            parser.prslextype::regprocedure::text
        )
    FROM pg_catalog.pg_ts_parser AS parser
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = parser.prsnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_ts_template',
        namespace.nspname,
        template.tmplname,
        concat_ws(
            ':',
            CASE WHEN template.tmplinit = 0 THEN '' ELSE template.tmplinit::regprocedure::text END,
            template.tmpllexize::regprocedure::text
        )
    FROM pg_catalog.pg_ts_template AS template
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = template.tmplnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'application_semantic_transform',
        namespace.nspname,
        transform.trftype::regtype::text || ':' || language.lanname,
        concat_ws(
            ':',
            CASE WHEN transform.trffromsql = 0 THEN '' ELSE transform.trffromsql::regprocedure::text END,
            CASE WHEN transform.trftosql = 0 THEN '' ELSE transform.trftosql::regprocedure::text END
        )
    FROM pg_catalog.pg_transform AS transform
    JOIN pg_catalog.pg_type AS type_row ON type_row.oid = transform.trftype
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    JOIN pg_catalog.pg_language AS language ON language.oid = transform.trflang
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'comment',
        namespace.nspname,
        'relation:' || relation.relname,
        description.description
    FROM pg_catalog.pg_description AS description
    JOIN pg_catalog.pg_class AS relation ON relation.oid = description.objoid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE description.classoid = 'pg_catalog.pg_class'::regclass
      AND description.objsubid = 0
      AND relation.relkind <> 't'::"char"
      AND namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'comment',
        namespace.nspname,
        'column:' || relation.relname || '.' || attribute.attname,
        description.description
    FROM pg_catalog.pg_description AS description
    JOIN pg_catalog.pg_class AS relation ON relation.oid = description.objoid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_attribute AS attribute
      ON attribute.attrelid = description.objoid
     AND attribute.attnum = description.objsubid
    WHERE description.classoid = 'pg_catalog.pg_class'::regclass
      AND description.objsubid > 0
      AND NOT attribute.attisdropped
      AND namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'comment',
        namespace.nspname,
        'routine:' || routine.proname || ':' ||
            pg_catalog.pg_get_function_identity_arguments(routine.oid),
        description.description
    FROM pg_catalog.pg_description AS description
    JOIN pg_catalog.pg_proc AS routine ON routine.oid = description.objoid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    WHERE description.classoid = 'pg_catalog.pg_proc'::regclass
      AND namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'comment',
        namespace.nspname,
        'constraint:' || COALESCE(relation.relname, type_row.typname, '?') || '.' ||
            constraint_row.conname || ':' || constraint_row.contype::text,
        description.description
    FROM pg_catalog.pg_description AS description
    JOIN pg_catalog.pg_constraint AS constraint_row ON constraint_row.oid = description.objoid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = constraint_row.connamespace
    LEFT JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_row.conrelid
    LEFT JOIN pg_catalog.pg_type AS type_row ON type_row.oid = constraint_row.contypid
    WHERE description.classoid = 'pg_catalog.pg_constraint'::regclass
      AND namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
        'event_trigger',
        '<cluster>',
        event_trigger.evtname,
        concat_ws(
            ':',
            event_trigger.evtevent,
            event_trigger.evtenabled,
            event_trigger.evtowner::regrole::text,
            COALESCE(
                (SELECT string_agg(tag, ',' ORDER BY tag)
                 FROM unnest(event_trigger.evttags) AS tag),
                ''
            ),
            event_trigger.evtfoid::regprocedure::text
        )
    FROM pg_catalog.pg_event_trigger AS event_trigger
    UNION ALL
    SELECT
        'public_residue_relation',
        'public',
        relation.relname,
        relation.relkind::text || ':' || relation.relowner::regrole::text || ':' ||
        COALESCE(relation.relacl::text, '')
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      -- version row/ACL은 controlled 0236→300 delta다. common catalog에는 그 밖의
      -- public residue만 남기고, exact source/destination facet은 dedicated sidecar가
      -- 각각 receipt화한다.
      AND NOT (relation.relkind = 'r' AND relation.relname = 'alembic_version')
      -- public에 놓인 extension 소유 relation은 application residue가 아니다. image가
      -- 가진 optional contrib extension 차이를 `0236 → 300` DDL drift로 오판하지 않는다.
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_class'::regclass
            AND extension_member.objid = relation.oid
            AND extension_member.refclassid = 'pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    -- ``public.alembic_version``은 active baseline metadata를 담는 유일한 public
    -- relation이다. 일반 public residue에서 이름만 예외로 두면 index/column ACL/RLS/
    -- trigger/rule/policy drift가 stamp 직전까지 보이지 않는다. 다만 table-level ACL과
    -- raw revision은 controlled handoff가 의도적으로 바꾸는 facet이므로 dedicated
    -- source/destination sidecar로 분리하고, 여기에는 나머지 physical contract를 남긴다.
    SELECT
        'public_alembic_version_contract',
        'public',
        relation.relname,
        jsonb_build_object(
            'extension_member', EXISTS (
                SELECT 1
                FROM pg_catalog.pg_depend AS extension_member
                WHERE extension_member.classid = 'pg_catalog.pg_class'::regclass
                  AND extension_member.objid = relation.oid
                  AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
                  AND extension_member.deptype = 'e'
            ),
            'relation', jsonb_build_object(
                'access_method', CASE
                    WHEN relation.relam = 0 THEN '<none>'
                    ELSE COALESCE(table_access_method.amname, '<missing>')
                END,
                -- ``relnatts`` counts physical attribute slots, including a slot left
                -- behind by ADD COLUMN + DROP COLUMN.  The live ``columns`` projection
                -- below intentionally omits dropped attributes for a readable logical
                -- contract, so bind the physical layout separately: otherwise a
                -- metadata-only handoff could accept a table whose catalog shape is not
                -- the Alembic table that the fresh root created.
                'attribute_slot_count', relation.relnatts,
                'force_row_security', relation.relforcerowsecurity,
                'kind', relation.relkind::text,
                'options', COALESCE((
                    SELECT jsonb_agg(option ORDER BY option)
                    FROM unnest(relation.reloptions) AS option
                ), '[]'::jsonb),
                'owner', relation.relowner::regrole::text,
                'persistence', relation.relpersistence::text,
                'replica_identity', relation.relreplident::text,
                'row_security', relation.relrowsecurity,
                'tablespace', CASE
                    WHEN relation.reltablespace = 0 THEN '<database-default>'
                    ELSE COALESCE(table_tablespace.spcname, '<missing>')
                END
            ),
            -- relation table ACL은 source/destination facet으로 분리되지만 implicit
            -- composite row type은 두 상태에서 동일해야 한다. type ACL은 relation ACL과
            -- 독립적으로 GRANT될 수 있으므로 typed ACL projection으로 exact receipt화한다.
            'row_type', COALESCE((
                SELECT jsonb_build_object(
                    'acl', COALESCE((
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'grantable', privilege.is_grantable,
                                'grantee', CASE
                                    WHEN privilege.grantee = 0 THEN 'PUBLIC'
                                    ELSE privilege.grantee::regrole::text
                                END,
                                'grantor', privilege.grantor::regrole::text,
                                'privilege', privilege.privilege_type
                            )
                            ORDER BY privilege.grantor,
                                     privilege.grantee,
                                     privilege.privilege_type,
                                     privilege.is_grantable
                        )
                        FROM aclexplode(type_row.typacl) AS privilege
                    ), '[]'::jsonb),
                    'array_type', COALESCE((
                        SELECT jsonb_build_object(
                            'acl', COALESCE((
                                SELECT jsonb_agg(
                                    jsonb_build_object(
                                        'grantable', privilege.is_grantable,
                                        'grantee', CASE
                                            WHEN privilege.grantee = 0 THEN 'PUBLIC'
                                            ELSE privilege.grantee::regrole::text
                                        END,
                                        'grantor', privilege.grantor::regrole::text,
                                        'privilege', privilege.privilege_type
                                    )
                                    ORDER BY privilege.grantor,
                                             privilege.grantee,
                                             privilege.privilege_type,
                                             privilege.is_grantable
                                )
                                FROM aclexplode(type_array.typacl) AS privilege
                            ), '[]'::jsonb),
                            'collation', CASE
                                WHEN type_array.typcollation = 0 THEN '<none>'
                                ELSE array_collation_namespace.nspname || '.'
                                    || array_collation.collname
                            END,
                            'defined', type_array.typisdefined,
                            'element', type_array.typelem::regtype::text,
                            'kind', type_array.typtype::text,
                            'name', type_array.typname,
                            'namespace', array_namespace.nspname,
                            'owner', type_array.typowner::regrole::text,
                            'relation_link', CASE
                                WHEN type_array.typrelid = 0 THEN '<none>'
                                ELSE type_array.typrelid::regclass::text
                            END,
                            'array_link', CASE
                                WHEN type_array.typarray = 0 THEN '<none>'
                                ELSE type_array.typarray::regtype::text
                            END
                        )
                        FROM pg_catalog.pg_type AS type_array
                        JOIN pg_catalog.pg_namespace AS array_namespace
                          ON array_namespace.oid = type_array.typnamespace
                        LEFT JOIN pg_catalog.pg_collation AS array_collation
                          ON array_collation.oid = type_array.typcollation
                        LEFT JOIN pg_catalog.pg_namespace AS array_collation_namespace
                          ON array_collation_namespace.oid = array_collation.collnamespace
                        WHERE type_array.oid = type_row.typarray
                    ), '{}'::jsonb),
                    'collation', CASE
                        WHEN type_row.typcollation = 0 THEN '<none>'
                        ELSE collation_namespace.nspname || '.' || type_collation.collname
                    END,
                    'defined', type_row.typisdefined,
                    'kind', type_row.typtype::text,
                    'name', type_row.typname,
                    'namespace', type_namespace.nspname,
                    'owner', type_row.typowner::regrole::text
                )
                FROM pg_catalog.pg_type AS type_row
                JOIN pg_catalog.pg_namespace AS type_namespace
                  ON type_namespace.oid = type_row.typnamespace
                LEFT JOIN pg_catalog.pg_collation AS type_collation
                  ON type_collation.oid = type_row.typcollation
                LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
                  ON collation_namespace.oid = type_collation.collnamespace
                WHERE type_row.typrelid = relation.oid
            ), '{}'::jsonb),
            'attribute_slots', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'dropped', attribute.attisdropped,
                        'number', attribute.attnum,
                        'type', CASE
                            WHEN attribute.attisdropped THEN '<dropped>'
                            ELSE pg_catalog.format_type(
                                attribute.atttypid,
                                attribute.atttypmod
                            )
                        END
                    )
                    ORDER BY attribute.attnum
                )
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid = relation.oid
                  AND attribute.attnum > 0
            ), '[]'::jsonb),
            'columns', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'acl', COALESCE(attribute.attacl::text, ''),
                        'compression', COALESCE(attribute.attcompression::text, ''),
                        'default', COALESCE(
                            pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid, true),
                            ''
                        ),
                        'dimensions', attribute.attndims,
                        'fdw_options', COALESCE((
                            SELECT jsonb_agg(option ORDER BY option)
                            FROM unnest(attribute.attfdwoptions) AS option
                        ), '[]'::jsonb),
                        'generated', attribute.attgenerated::text,
                        'identity', attribute.attidentity::text,
                        'name', attribute.attname,
                        'not_null', attribute.attnotnull,
                        'number', attribute.attnum,
                        'options', COALESCE((
                            SELECT jsonb_agg(option ORDER BY option)
                            FROM unnest(attribute.attoptions) AS option
                        ), '[]'::jsonb),
                        'statistics_target', attribute.attstattarget,
                        'storage', attribute.attstorage::text,
                        'type', pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                    )
                    ORDER BY attribute.attnum
                )
                FROM pg_catalog.pg_attribute AS attribute
                LEFT JOIN pg_catalog.pg_attrdef AS default_row
                  ON default_row.adrelid = attribute.attrelid
                 AND default_row.adnum = attribute.attnum
                WHERE attribute.attrelid = relation.oid
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ), '[]'::jsonb),
            'constraints', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'deferred', constraint_row.condeferred,
                        'deferrable', constraint_row.condeferrable,
                        'definition', pg_catalog.pg_get_constraintdef(constraint_row.oid, true),
                        'inherited_count', constraint_row.coninhcount,
                        'local', constraint_row.conislocal,
                        'name', constraint_row.conname,
                        'no_inherit', constraint_row.connoinherit,
                        'type', constraint_row.contype::text,
                        'validated', constraint_row.convalidated
                    )
                    ORDER BY constraint_row.oid
                )
                FROM pg_catalog.pg_constraint AS constraint_row
                WHERE constraint_row.conrelid = relation.oid
            ), '[]'::jsonb),
            'indexes', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'acl', COALESCE(index_relation.relacl::text, ''),
                        'access_method', CASE
                            WHEN index_relation.relam = 0 THEN '<none>'
                            ELSE COALESCE(index_access_method.amname, '<missing>')
                        END,
                        'definition', pg_catalog.pg_get_indexdef(index_row.indexrelid),
                        'expression', COALESCE(
                            pg_catalog.pg_get_expr(index_row.indexprs, index_row.indrelid, true),
                            ''
                        ),
                        'indclass', index_row.indclass::text,
                        'indcollation', index_row.indcollation::text,
                        'indkey', index_row.indkey::text,
                        'indoption', index_row.indoption::text,
                        'is_clustered', index_row.indisclustered,
                        'is_live', index_row.indislive,
                        'is_primary', index_row.indisprimary,
                        'is_ready', index_row.indisready,
                        'is_replica_identity', index_row.indisreplident,
                        'is_unique', index_row.indisunique,
                        'is_valid', index_row.indisvalid,
                        'name', index_relation.relname,
                        'nulls_not_distinct', index_row.indnullsnotdistinct,
                        'options', COALESCE((
                            SELECT jsonb_agg(option ORDER BY option)
                            FROM unnest(index_relation.reloptions) AS option
                        ), '[]'::jsonb),
                        'owner', index_relation.relowner::regrole::text,
                        'predicate', COALESCE(
                            pg_catalog.pg_get_expr(index_row.indpred, index_row.indrelid, true),
                            ''
                        ),
                        'tablespace', CASE
                            WHEN index_relation.reltablespace = 0 THEN '<database-default>'
                            ELSE COALESCE(index_tablespace.spcname, '<missing>')
                        END
                    )
                    ORDER BY index_relation.oid
                )
                FROM pg_catalog.pg_index AS index_row
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_row.indexrelid
                LEFT JOIN pg_catalog.pg_am AS index_access_method
                  ON index_access_method.oid = index_relation.relam
                LEFT JOIN pg_catalog.pg_tablespace AS index_tablespace
                  ON index_tablespace.oid = index_relation.reltablespace
                WHERE index_row.indrelid = relation.oid
            ), '[]'::jsonb),
            'policies', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'command', policy.polcmd::text,
                        'name', policy.polname,
                        'permissive', policy.polpermissive,
                        'qual', COALESCE(
                            pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
                            ''
                        ),
                        'roles', COALESCE((
                            SELECT jsonb_agg(role.rolname ORDER BY role.rolname)
                            FROM unnest(policy.polroles) AS role_oid
                            JOIN pg_catalog.pg_roles AS role ON role.oid = role_oid
                        ), '[]'::jsonb),
                        'with_check', COALESCE(
                            pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true),
                            ''
                        )
                    )
                    ORDER BY policy.oid
                )
                FROM pg_catalog.pg_policy AS policy
                WHERE policy.polrelid = relation.oid
            ), '[]'::jsonb),
            'rules', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'definition', pg_catalog.pg_get_ruledef(rule.oid, true),
                        'enabled', rule.ev_enabled::text,
                        'event', rule.ev_type::text,
                        'instead', rule.is_instead,
                        'name', rule.rulename
                    )
                    ORDER BY rule.oid
                )
                FROM pg_catalog.pg_rewrite AS rule
                WHERE rule.ev_class = relation.oid
                  AND rule.rulename <> '_RETURN'
            ), '[]'::jsonb),
            'triggers', COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'arguments', encode(trigger.tgargs, 'hex'),
                        'definition', pg_catalog.pg_get_triggerdef(trigger.oid, true),
                        'enabled', trigger.tgenabled::text,
                        'name', trigger.tgname,
                        'type', trigger.tgtype
                    )
                    ORDER BY trigger.oid
                )
                FROM pg_catalog.pg_trigger AS trigger
                WHERE trigger.tgrelid = relation.oid
                  AND NOT trigger.tgisinternal
            ), '[]'::jsonb)
        )::text
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_am AS table_access_method
      ON table_access_method.oid = relation.relam
    LEFT JOIN pg_catalog.pg_tablespace AS table_tablespace
      ON table_tablespace.oid = relation.reltablespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind = 'r'
      AND relation.relname = 'alembic_version'
    UNION ALL
    SELECT
        'public_residue_routine',
        'public',
        routine.proname || ':' || pg_catalog.pg_get_function_identity_arguments(routine.oid),
        routine.proowner::regrole::text || ':' || COALESCE(routine.proacl::text, '') || ':' ||
        pg_catalog.pg_get_functiondef(routine.oid)
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname = 'public'
      -- 위 relation과 같은 이유로 extension member function은 public residue receipt의
      -- 대상이 아니다. 임의 사용자가 만든 public routine은 계속 exact receipt에 남는다.
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_proc'::regclass
            AND extension_member.objid = routine.oid
            AND extension_member.refclassid = 'pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_type',
        'public',
        type_row.typname,
        concat_ws(
            ':',
            type_row.typtype,
            type_row.typcategory,
            type_row.typnotnull,
            type_row.typbasetype::regtype::text,
            type_row.typtypmod,
            type_row.typowner::regrole::text,
            COALESCE(type_row.typacl::text, ''),
            CASE
                WHEN type_row.typcollation = 0 THEN ''
                ELSE type_row.typcollation::regcollation::text
            END,
            COALESCE(
                pg_catalog.pg_get_expr(type_row.typdefaultbin, 0, true),
                type_row.typdefault,
                ''
            )
        )
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname = 'public'
      AND type_row.typrelid = 0
      AND type_row.typelem = 0
      AND type_row.typisdefined
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_type'::regclass
            AND extension_member.objid = type_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_collation',
        'public',
        collation_row.collname,
        concat_ws(
            ':',
            collation_row.collowner::regrole::text,
            collation_row.collprovider,
            collation_row.collisdeterministic,
            collation_row.collencoding,
            COALESCE(collation_row.collcollate, ''),
            COALESCE(collation_row.collctype, ''),
            COALESCE(collation_row.colliculocale, ''),
            COALESCE(collation_row.collicurules, ''),
            COALESCE(collation_row.collversion, '')
        )
    FROM pg_catalog.pg_collation AS collation_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = collation_row.collnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_collation'::regclass
            AND extension_member.objid = collation_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_operator',
        'public',
        operator_row.oid::regoperator::text,
        concat_ws(
            ':',
            operator_row.oprowner::regrole::text,
            operator_row.oprkind,
            operator_row.oprleft::regtype::text,
            operator_row.oprright::regtype::text,
            operator_row.oprresult::regtype::text,
            operator_row.oprcode::regprocedure::text,
            COALESCE(operator_row.oprrest::regprocedure::text, ''),
            COALESCE(operator_row.oprjoin::regprocedure::text, '')
        )
    FROM pg_catalog.pg_operator AS operator_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_row.oprnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_operator'::regclass
            AND extension_member.objid = operator_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_cast',
        'public',
        cast_row.castsource::regtype::text || '->' || cast_row.casttarget::regtype::text,
        concat_ws(
            ':',
            cast_row.castcontext,
            cast_row.castmethod,
            CASE WHEN cast_row.castfunc = 0 THEN '' ELSE cast_row.castfunc::regprocedure::text END
        )
    FROM pg_catalog.pg_cast AS cast_row
    JOIN pg_catalog.pg_type AS source_type ON source_type.oid = cast_row.castsource
    JOIN pg_catalog.pg_type AS target_type ON target_type.oid = cast_row.casttarget
    JOIN pg_catalog.pg_namespace AS source_namespace ON source_namespace.oid = source_type.typnamespace
    JOIN pg_catalog.pg_namespace AS target_namespace ON target_namespace.oid = target_type.typnamespace
    WHERE (source_namespace.nspname = 'public' OR target_namespace.nspname = 'public')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_cast'::regclass
            AND extension_member.objid = cast_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_conversion',
        'public',
        conversion.conname,
        concat_ws(
            ':',
            conversion.conowner::regrole::text,
            conversion.conforencoding,
            conversion.contoencoding,
            conversion.conproc::regprocedure::text,
            conversion.condefault
        )
    FROM pg_catalog.pg_conversion AS conversion
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = conversion.connamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_conversion'::regclass
            AND extension_member.objid = conversion.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_opfamily',
        'public',
        family.opfname,
        family.opfowner::regrole::text || ':' || access_method.amname
    FROM pg_catalog.pg_opfamily AS family
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = family.opfmethod
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_opfamily'::regclass
            AND extension_member.objid = family.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_opclass',
        'public',
        operator_class.opcname,
        concat_ws(
            ':',
            operator_class.opcowner::regrole::text,
            access_method.amname,
            family.opfname,
            operator_class.opcintype::regtype::text,
            operator_class.opcdefault,
            CASE
                WHEN operator_class.opckeytype = 0 THEN ''
                ELSE operator_class.opckeytype::regtype::text
            END
        )
    FROM pg_catalog.pg_opclass AS operator_class
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_class.opcnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = operator_class.opcmethod
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = operator_class.opcfamily
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_opclass'::regclass
            AND extension_member.objid = operator_class.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_amop',
        'public',
        family.opfname || ':' || operator_row.oid::regoperator::text,
        concat_ws(
            ':',
            amop.amopstrategy,
            amop.amoppurpose,
            CASE
                WHEN amop.amopsortfamily = 0 THEN ''
                ELSE sort_namespace.nspname || '.' || sort_family.opfname
            END
        )
    FROM pg_catalog.pg_amop AS amop
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = amop.amopfamily
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_operator AS operator_row ON operator_row.oid = amop.amopopr
    LEFT JOIN pg_catalog.pg_opfamily AS sort_family ON sort_family.oid = amop.amopsortfamily
    LEFT JOIN pg_catalog.pg_namespace AS sort_namespace ON sort_namespace.oid = sort_family.opfnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
            AND extension_member.classid = 'pg_catalog.pg_opfamily'::regclass
            AND extension_member.objid = family.oid
      )
    UNION ALL
    SELECT
        'public_residue_amproc',
        'public',
        family.opfname || ':' || amproc.amproclefttype::regtype::text || ':' ||
            amproc.amprocrighttype::regtype::text || ':' || amproc.amprocnum::text,
        amproc.amproc::regprocedure::text
    FROM pg_catalog.pg_amproc AS amproc
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = amproc.amprocfamily
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
            AND extension_member.classid = 'pg_catalog.pg_opfamily'::regclass
            AND extension_member.objid = family.oid
      )
    UNION ALL
    SELECT
        'public_residue_ts_config',
        'public',
        configuration.cfgname,
        configuration.cfgowner::regrole::text || ':' ||
            parser_namespace.nspname || '.' || parser.prsname
    FROM pg_catalog.pg_ts_config AS configuration
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
    JOIN pg_catalog.pg_ts_parser AS parser ON parser.oid = configuration.cfgparser
    JOIN pg_catalog.pg_namespace AS parser_namespace ON parser_namespace.oid = parser.prsnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_ts_config'::regclass
            AND extension_member.objid = configuration.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_ts_config_map',
        'public',
        configuration.cfgname || ':' || mapping.maptokentype::text || ':' ||
            mapping.mapseqno::text,
        mapping.mapdict::regdictionary::text
    FROM pg_catalog.pg_ts_config_map AS mapping
    JOIN pg_catalog.pg_ts_config AS configuration ON configuration.oid = mapping.mapcfg
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_ts_config'::regclass
            AND extension_member.objid = configuration.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_ts_dictionary',
        'public',
        dictionary.dictname,
        concat_ws(
            ':',
            dictionary.dictowner::regrole::text,
            template_namespace.nspname || '.' || template.tmplname,
            COALESCE(dictionary.dictinitoption, '')
        )
    FROM pg_catalog.pg_ts_dict AS dictionary
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = dictionary.dictnamespace
    JOIN pg_catalog.pg_ts_template AS template ON template.oid = dictionary.dicttemplate
    JOIN pg_catalog.pg_namespace AS template_namespace ON template_namespace.oid = template.tmplnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_ts_dict'::regclass
            AND extension_member.objid = dictionary.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_ts_parser',
        'public',
        parser.prsname,
        concat_ws(
            ':',
            parser.prsstart::regprocedure::text,
            parser.prstoken::regprocedure::text,
            parser.prsend::regprocedure::text,
            parser.prsheadline::regprocedure::text,
            parser.prslextype::regprocedure::text
        )
    FROM pg_catalog.pg_ts_parser AS parser
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = parser.prsnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_ts_parser'::regclass
            AND extension_member.objid = parser.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_ts_template',
        'public',
        template.tmplname,
        concat_ws(
            ':',
            CASE WHEN template.tmplinit = 0 THEN '' ELSE template.tmplinit::regprocedure::text END,
            template.tmpllexize::regprocedure::text
        )
    FROM pg_catalog.pg_ts_template AS template
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = template.tmplnamespace
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_ts_template'::regclass
            AND extension_member.objid = template.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_transform',
        'public',
        transform.trftype::regtype::text || ':' || language.lanname,
        concat_ws(
            ':',
            CASE WHEN transform.trffromsql = 0 THEN '' ELSE transform.trffromsql::regprocedure::text END,
            CASE WHEN transform.trftosql = 0 THEN '' ELSE transform.trftosql::regprocedure::text END
        )
    FROM pg_catalog.pg_transform AS transform
    JOIN pg_catalog.pg_type AS type_row ON type_row.oid = transform.trftype
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    JOIN pg_catalog.pg_language AS language ON language.oid = transform.trflang
    WHERE namespace.nspname = 'public'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_transform'::regclass
            AND extension_member.objid = transform.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'public_residue_foreign_data_wrapper',
        '<cluster>',
        wrapper.fdwname,
        concat_ws(
            ':',
            wrapper.fdwowner::regrole::text,
            CASE WHEN wrapper.fdwhandler = 0 THEN '' ELSE wrapper.fdwhandler::regproc::text END,
            CASE WHEN wrapper.fdwvalidator = 0 THEN '' ELSE wrapper.fdwvalidator::regproc::text END,
            COALESCE(wrapper.fdwacl::text, '')
        )
    FROM pg_catalog.pg_foreign_data_wrapper AS wrapper
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS extension_member
        WHERE extension_member.classid = 'pg_catalog.pg_foreign_data_wrapper'::regclass
          AND extension_member.objid = wrapper.oid
          AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
          AND extension_member.deptype = 'e'
    )
    UNION ALL
    SELECT
        'public_residue_foreign_server',
        '<cluster>',
        server.srvname,
        concat_ws(
            ':',
            server.srvowner::regrole::text,
            wrapper.fdwname,
            COALESCE(server.srvtype, ''),
            COALESCE(server.srvversion, '')
        )
    FROM pg_catalog.pg_foreign_server AS server
    JOIN pg_catalog.pg_foreign_data_wrapper AS wrapper ON wrapper.oid = server.srvfdw
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS extension_member
        WHERE extension_member.classid = 'pg_catalog.pg_foreign_server'::regclass
          AND extension_member.objid = server.oid
          AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
          AND extension_member.deptype = 'e'
    )
    UNION ALL
    SELECT
        'x_extension_residue_relation',
        'x_extension',
        relation.relname,
        relation.relkind::text || ':' || relation.relowner::regrole::text || ':' ||
        COALESCE(relation.relacl::text, '')
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'x_extension'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_class'::regclass
            AND extension_member.objid = relation.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'x_extension_residue_routine',
        'x_extension',
        routine.proname || ':' || pg_catalog.pg_get_function_identity_arguments(routine.oid),
        routine.proowner::regrole::text || ':' || COALESCE(routine.proacl::text, '')
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname = 'x_extension'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_proc'::regclass
            AND extension_member.objid = routine.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'x_extension_residue_type',
        'x_extension',
        type_row.typname,
        type_row.typtype::text || ':' || type_row.typowner::regrole::text || ':' ||
        CASE WHEN type_row.typcollation = 0 THEN '' ELSE type_row.typcollation::regcollation::text END
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname = 'x_extension'
      AND type_row.typrelid = 0
      AND type_row.typelem = 0
      AND type_row.typisdefined
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_type'::regclass
            AND extension_member.objid = type_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'x_extension_residue_collation',
        'x_extension',
        collation_row.collname,
        collation_row.collowner::regrole::text || ':' || collation_row.collprovider::text || ':' ||
        collation_row.collisdeterministic::text
    FROM pg_catalog.pg_collation AS collation_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = collation_row.collnamespace
    WHERE namespace.nspname = 'x_extension'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_collation'::regclass
            AND extension_member.objid = collation_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'x_extension_residue_operator',
        'x_extension',
        operator_row.oid::regoperator::text,
        operator_row.oprowner::regrole::text || ':' || operator_row.oprcode::regprocedure::text
    FROM pg_catalog.pg_operator AS operator_row
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_row.oprnamespace
    WHERE namespace.nspname = 'x_extension'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_operator'::regclass
            AND extension_member.objid = operator_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    SELECT
        'x_extension_residue_cast',
        'x_extension',
        cast_row.castsource::regtype::text || '->' || cast_row.casttarget::regtype::text,
        cast_row.castcontext::text || ':' || cast_row.castmethod::text || ':' ||
        CASE WHEN cast_row.castfunc = 0 THEN '' ELSE cast_row.castfunc::regprocedure::text END
    FROM pg_catalog.pg_cast AS cast_row
    JOIN pg_catalog.pg_type AS source_type ON source_type.oid = cast_row.castsource
    JOIN pg_catalog.pg_type AS target_type ON target_type.oid = cast_row.casttarget
    JOIN pg_catalog.pg_namespace AS source_namespace ON source_namespace.oid = source_type.typnamespace
    JOIN pg_catalog.pg_namespace AS target_namespace ON target_namespace.oid = target_type.typnamespace
    WHERE (source_namespace.nspname = 'x_extension' OR target_namespace.nspname = 'x_extension')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_catalog.pg_depend AS extension_member
          WHERE extension_member.classid = 'pg_catalog.pg_cast'::regclass
            AND extension_member.objid = cast_row.oid
            AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
            AND extension_member.deptype = 'e'
      )
    UNION ALL
    -- extension member는 extension header와 별개로 직접 ALTER/GRANT될 수 있다. member
    -- inventory와 개별 semantic definition을 모두 receipt화한다. 그러면 source image와
    -- extension version이 같아도 function body, operator family, table ACL/data drift가
    -- metadata handoff를 통과하지 못한다.
    SELECT
        'extension_member_inventory',
        member.extension_schema,
        member.extension_name || ':' || member.classid::regclass::text,
        (pg_catalog.pg_identify_object(member.classid, member.objid, 0)).identity
    FROM extension_member AS member
    UNION ALL
    SELECT
        'extension_member_relation',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname,
        concat_ws(
            ':',
            relation.relkind,
            CASE WHEN relation.relam = 0 THEN '<none>'
                 ELSE COALESCE(access_method.amname, '<missing>') END,
            owner.canonical_name,
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(
                            '/',
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                        ),
                        ',' ORDER BY
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                    )
                    FROM aclexplode(relation.relacl) AS privilege
                    LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                    JOIN role_class AS grantor ON grantor.oid = privilege.grantor
                ),
                ''
            ),
            relation.relrowsecurity,
            relation.relforcerowsecurity,
            relation.relpersistence,
            relation.relreplident,
            CASE WHEN relation.reltablespace = 0 THEN '<default>'
                 ELSE COALESCE(tablespace.spcname, '<missing>') END,
            COALESCE(pg_catalog.pg_get_expr(relation.relpartbound, relation.oid, true), ''),
            COALESCE(
                (SELECT string_agg(option, ',' ORDER BY option)
                 FROM unnest(relation.reloptions) AS option),
                ''
            ),
            CASE WHEN relation.relkind IN ('v', 'm')
                 THEN pg_catalog.pg_get_viewdef(relation.oid, true)
                 ELSE '' END
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN role_class AS owner ON owner.oid = relation.relowner
    LEFT JOIN pg_catalog.pg_am AS access_method ON access_method.oid = relation.relam
    LEFT JOIN pg_catalog.pg_tablespace AS tablespace ON tablespace.oid = relation.reltablespace
    UNION ALL
    SELECT
        'extension_member_column',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname,
        attribute.attnum::text || ':' || attribute.attname || ':' ||
        pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) || ':' ||
        attribute.attnotnull::text || ':' || attribute.attidentity::text || ':' ||
        attribute.attgenerated::text || ':' || attribute.attndims::text || ':' ||
        attribute.atthasdef::text || ':' || attribute.attislocal::text || ':' ||
        attribute.attinhcount::text || ':' ||
        CASE WHEN attribute.attcollation = 0 THEN ''
             ELSE attribute.attcollation::regcollation::text END || ':' ||
        COALESCE(
            (
                SELECT string_agg(
                    concat_ws(
                        '/',
                        CASE WHEN privilege.grantee = 0 THEN 'public'
                             ELSE grantee.canonical_name END,
                        grantor.canonical_name,
                        privilege.privilege_type,
                        privilege.is_grantable
                    ),
                    ',' ORDER BY
                        CASE WHEN privilege.grantee = 0 THEN 'public'
                             ELSE grantee.canonical_name END,
                        grantor.canonical_name,
                        privilege.privilege_type,
                        privilege.is_grantable
                )
                FROM aclexplode(attribute.attacl) AS privilege
                LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                JOIN role_class AS grantor ON grantor.oid = privilege.grantor
            ),
            ''
        ) || ':' ||
        COALESCE(pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid), '') || ':' ||
        attribute.attstattarget::text || ':' ||
        COALESCE((SELECT string_agg(option, ',' ORDER BY option)
                  FROM unnest(attribute.attoptions) AS option), '') || ':' ||
        COALESCE((SELECT string_agg(option, ',' ORDER BY option)
                  FROM unnest(attribute.attfdwoptions) AS option), '') || ':' ||
        attribute.attstorage::text || ':' || COALESCE(attribute.attcompression::text, '')
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = relation.oid
    LEFT JOIN pg_catalog.pg_attrdef AS default_row
      ON default_row.adrelid = attribute.attrelid
     AND default_row.adnum = attribute.attnum
    WHERE attribute.attnum > 0
      AND NOT attribute.attisdropped
    UNION ALL
    -- Extension-owned ordinary table rows, particularly `postgis.extconfig`, are
    -- data-bearing semantics. Build a typed JSON row projection dynamically so
    -- column names/types are part of the digest, sort the projection in the SQL
    -- itself, and emit only its SHA-256 (never data/options plaintext).
    SELECT
        'extension_member_table_data',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname,
        encode(
            x_extension.digest(
                convert_to(
                    xmlserialize(
                        CONTENT pg_catalog.query_to_xml(canonical.query, false, true, '')
                        AS text
                    ),
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL (
        SELECT string_agg(
            format(
                '%L, jsonb_build_object(''type'', %L, ''value'', to_jsonb(source) -> %L)',
                attribute.attname,
                pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                attribute.attname
            ),
            ', ' ORDER BY attribute.attnum
        ) AS typed_columns
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = relation.oid
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) AS columns
    CROSS JOIN LATERAL (
        SELECT format(
            'SELECT item FROM (SELECT jsonb_build_object(%s)::text AS item FROM %s AS source) '
            || 'AS typed ORDER BY item COLLATE "C"',
            columns.typed_columns,
            relation.oid::regclass
        ) AS query
    ) AS canonical
    WHERE relation.relkind IN ('r', 'p')
      AND columns.typed_columns IS NOT NULL
    UNION ALL
    -- pg_extension.extconfig는 member dependency와 별개의 authoritative config-table
    -- inventory다. member link를 삭제하거나 다른 relation으로 바꿔도 extconfig의
    -- ordinal·relation·typed rows가 receipt에서 사라지지 않게 독립적으로 hash한다.
    SELECT
        'extension_config_table_data',
        namespace.nspname,
        extension.extname || ':' || config.ordinality::text || ':' ||
            namespace.nspname || '.' || relation.relname,
        encode(
            x_extension.digest(
                convert_to(
                    xmlserialize(
                        CONTENT pg_catalog.query_to_xml(canonical.query, false, true, '')
                        AS text
                    ),
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    FROM pg_catalog.pg_extension AS extension
    CROSS JOIN LATERAL unnest(extension.extconfig) WITH ORDINALITY
      AS config(relation_oid, ordinality)
    JOIN pg_catalog.pg_class AS relation ON relation.oid = config.relation_oid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL (
        SELECT string_agg(
            format(
                '%L, jsonb_build_object(''type'', %L, ''value'', to_jsonb(source) -> %L)',
                attribute.attname,
                pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                attribute.attname
            ),
            ', ' ORDER BY attribute.attnum
        ) AS typed_columns
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = relation.oid
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) AS columns
    CROSS JOIN LATERAL (
        SELECT format(
            'SELECT item FROM (SELECT jsonb_build_object(%s)::text AS item FROM %s AS source) '
            || 'AS typed ORDER BY item COLLATE "C"',
            columns.typed_columns,
            relation.oid::regclass
        ) AS query
    ) AS canonical
    WHERE relation.relkind IN ('r', 'p')
      AND columns.typed_columns IS NOT NULL
    UNION ALL
    SELECT
        'extension_member_constraint',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname || ':' ||
            constraint_row.conname,
        concat_ws(
            ':',
            constraint_row.contype,
            constraint_row.condeferrable,
            constraint_row.condeferred,
            constraint_row.convalidated,
            constraint_row.connoinherit,
            COALESCE(pg_catalog.pg_get_constraintdef(constraint_row.oid, true), '')
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_constraint AS constraint_row ON constraint_row.conrelid = relation.oid
    UNION ALL
    SELECT
        'extension_member_index',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname || ':' ||
            index_relation.relname,
        concat_ws(
            ':',
            index_link.indisvalid,
            index_link.indisready,
            index_link.indislive,
            index_link.indisreplident,
            COALESCE((SELECT string_agg(option, ',' ORDER BY option)
                      FROM unnest(index_relation.reloptions) AS option), ''),
            pg_catalog.pg_get_indexdef(index_relation.oid)
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_index AS index_link ON index_link.indrelid = relation.oid
    JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index_link.indexrelid
    UNION ALL
    SELECT
        'extension_member_trigger',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname || ':' ||
            trigger_row.tgname,
        trigger_row.tgenabled::text || ':' || pg_catalog.pg_get_triggerdef(trigger_row.oid, true)
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_trigger AS trigger_row ON trigger_row.tgrelid = relation.oid
    WHERE NOT trigger_row.tgisinternal
    UNION ALL
    SELECT
        'extension_member_rule',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || relation.relname || ':' ||
            rewrite_row.rulename,
        pg_catalog.pg_get_ruledef(rewrite_row.oid, true)
    FROM extension_member AS member
    JOIN pg_catalog.pg_class AS relation
      ON member.classid = 'pg_catalog.pg_class'::regclass
     AND relation.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_rewrite AS rewrite_row ON rewrite_row.ev_class = relation.oid
    UNION ALL
    SELECT
        'extension_member_routine',
        member.extension_schema,
        member.extension_name || ':' || routine.oid::regprocedure::text,
        concat_ws(
            ':',
            owner.canonical_name,
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(
                            '/',
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                        ),
                        ',' ORDER BY
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                    )
                    FROM aclexplode(routine.proacl) AS privilege
                    LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                    JOIN role_class AS grantor ON grantor.oid = privilege.grantor
                ),
                ''
            ),
            routine.prokind,
            routine.prosecdef,
            routine.proleakproof,
            routine.proisstrict,
            routine.provolatile,
            routine.proparallel,
            routine.procost,
            routine.prorows,
            CASE WHEN routine.prosupport = 0 THEN '' ELSE routine.prosupport::regprocedure::text END,
            COALESCE(array_to_string(routine.proconfig, chr(30)), ''),
            CASE
                WHEN routine.prokind = 'a' THEN concat_ws(
                    chr(31),
                    'aggregate',
                    aggregate.aggkind,
                    aggregate.aggnumdirectargs,
                    CASE WHEN aggregate.aggtransfn = 0 THEN '' ELSE aggregate.aggtransfn::regprocedure::text END,
                    CASE WHEN aggregate.aggfinalfn = 0 THEN '' ELSE aggregate.aggfinalfn::regprocedure::text END,
                    CASE WHEN aggregate.aggcombinefn = 0 THEN '' ELSE aggregate.aggcombinefn::regprocedure::text END,
                    CASE WHEN aggregate.aggserialfn = 0 THEN '' ELSE aggregate.aggserialfn::regprocedure::text END,
                    CASE WHEN aggregate.aggdeserialfn = 0 THEN '' ELSE aggregate.aggdeserialfn::regprocedure::text END,
                    CASE WHEN aggregate.aggmtransfn = 0 THEN '' ELSE aggregate.aggmtransfn::regprocedure::text END,
                    CASE WHEN aggregate.aggminvtransfn = 0 THEN '' ELSE aggregate.aggminvtransfn::regprocedure::text END,
                    CASE WHEN aggregate.aggmfinalfn = 0 THEN '' ELSE aggregate.aggmfinalfn::regprocedure::text END,
                    aggregate.aggfinalextra,
                    aggregate.aggmfinalextra,
                    aggregate.aggfinalmodify,
                    aggregate.aggmfinalmodify,
                    CASE WHEN aggregate.aggsortop = 0 THEN '' ELSE aggregate.aggsortop::regoperator::text END,
                    aggregate.aggtranstype::regtype::text,
                    aggregate.aggtransspace,
                    aggregate.aggmtranstype::regtype::text,
                    aggregate.aggmtransspace,
                    COALESCE(aggregate.agginitval, ''),
                    COALESCE(aggregate.aggminitval, '')
                )
                ELSE pg_catalog.pg_get_functiondef(routine.oid)
            END
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_proc AS routine
      ON member.classid = 'pg_catalog.pg_proc'::regclass
     AND routine.oid = member.objid
    JOIN role_class AS owner ON owner.oid = routine.proowner
    LEFT JOIN pg_catalog.pg_aggregate AS aggregate ON aggregate.aggfnoid = routine.oid
    UNION ALL
    SELECT
        'extension_member_type',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || type_row.typname,
        concat_ws(
            ':',
            type_row.typtype,
            type_row.typcategory,
            type_row.typispreferred,
            type_row.typnotnull,
            type_row.typrelid::regclass::text,
            type_row.typelem::regtype::text,
            type_row.typinput::regprocedure::text,
            type_row.typoutput::regprocedure::text,
            type_row.typreceive::regprocedure::text,
            type_row.typsend::regprocedure::text,
            type_row.typmodin::regprocedure::text,
            type_row.typmodout::regprocedure::text,
            type_row.typanalyze::regprocedure::text,
            type_row.typbasetype::regtype::text,
            type_row.typtypmod,
            owner.canonical_name,
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(
                            '/',
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                        ),
                        ',' ORDER BY
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                    )
                    FROM aclexplode(type_row.typacl) AS privilege
                    LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                    JOIN role_class AS grantor ON grantor.oid = privilege.grantor
                ),
                ''
            ),
            CASE WHEN type_row.typcollation = 0 THEN ''
                 ELSE type_row.typcollation::regcollation::text END,
            COALESCE(pg_catalog.pg_get_expr(type_row.typdefaultbin, 0, true), type_row.typdefault, '')
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_type AS type_row
      ON member.classid = 'pg_catalog.pg_type'::regclass
     AND type_row.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    JOIN role_class AS owner ON owner.oid = type_row.typowner
    UNION ALL
    SELECT
        'extension_member_operator',
        member.extension_schema,
        member.extension_name || ':' || operator_row.oid::regoperator::text,
        concat_ws(
            ':',
            owner.canonical_name,
            operator_row.oprkind,
            operator_row.oprleft::regtype::text,
            operator_row.oprright::regtype::text,
            operator_row.oprresult::regtype::text,
            operator_row.oprcode::regprocedure::text,
            CASE WHEN operator_row.oprrest = 0 THEN '' ELSE operator_row.oprrest::regprocedure::text END,
            CASE WHEN operator_row.oprjoin = 0 THEN '' ELSE operator_row.oprjoin::regprocedure::text END,
            operator_row.oprcanmerge,
            operator_row.oprcanhash
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_operator AS operator_row
      ON member.classid = 'pg_catalog.pg_operator'::regclass
     AND operator_row.oid = member.objid
    JOIN role_class AS owner ON owner.oid = operator_row.oprowner
    UNION ALL
    SELECT
        'extension_member_cast',
        member.extension_schema,
        member.extension_name || ':' || cast_row.castsource::regtype::text || '->' ||
            cast_row.casttarget::regtype::text,
        concat_ws(
            ':',
            cast_row.castcontext,
            cast_row.castmethod,
            CASE WHEN cast_row.castfunc = 0 THEN '' ELSE cast_row.castfunc::regprocedure::text END
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_cast AS cast_row
      ON member.classid = 'pg_catalog.pg_cast'::regclass
     AND cast_row.oid = member.objid
    UNION ALL
    SELECT
        'extension_member_opfamily',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || family.opfname,
        owner.canonical_name || ':' || access_method.amname
    FROM extension_member AS member
    JOIN pg_catalog.pg_opfamily AS family
      ON member.classid = 'pg_catalog.pg_opfamily'::regclass
     AND family.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = family.opfmethod
    JOIN role_class AS owner ON owner.oid = family.opfowner
    UNION ALL
    SELECT
        'extension_member_opclass',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || class.opcname,
        concat_ws(
            ':',
            owner.canonical_name,
            access_method.amname,
            family.opfname,
            class.opcintype::regtype::text,
            class.opcdefault,
            CASE WHEN class.opckeytype = 0 THEN '' ELSE class.opckeytype::regtype::text END
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_opclass AS class
      ON member.classid = 'pg_catalog.pg_opclass'::regclass
     AND class.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = class.opcnamespace
    JOIN pg_catalog.pg_am AS access_method ON access_method.oid = class.opcmethod
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = class.opcfamily
    JOIN role_class AS owner ON owner.oid = class.opcowner
    UNION ALL
    SELECT
        'extension_member_amop',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || family.opfname || ':' ||
            operator_row.oid::regoperator::text,
        concat_ws(
            ':',
            amop.amopstrategy,
            amop.amoppurpose,
            CASE WHEN amop.amopsortfamily = 0 THEN ''
                 ELSE sort_namespace.nspname || '.' || sort_family.opfname END
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_opfamily AS family
      ON member.classid = 'pg_catalog.pg_opfamily'::regclass
     AND family.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_amop AS amop ON amop.amopfamily = family.oid
    JOIN pg_catalog.pg_operator AS operator_row ON operator_row.oid = amop.amopopr
    LEFT JOIN pg_catalog.pg_opfamily AS sort_family ON sort_family.oid = amop.amopsortfamily
    LEFT JOIN pg_catalog.pg_namespace AS sort_namespace
      ON sort_namespace.oid = sort_family.opfnamespace
    UNION ALL
    SELECT
        'extension_member_amproc',
        member.extension_schema,
        member.extension_name || ':' || namespace.nspname || '.' || family.opfname || ':' ||
            amproc.amproclefttype::regtype::text || ':' || amproc.amprocrighttype::regtype::text || ':' ||
            amproc.amprocnum::text,
        amproc.amproc::regprocedure::text
    FROM extension_member AS member
    JOIN pg_catalog.pg_opfamily AS family
      ON member.classid = 'pg_catalog.pg_opfamily'::regclass
     AND family.oid = member.objid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    JOIN pg_catalog.pg_amproc AS amproc ON amproc.amprocfamily = family.oid
    UNION ALL
    SELECT
        'extension_member_language',
        member.extension_schema,
        member.extension_name || ':' || language.lanname,
        concat_ws(
            ':',
            owner.canonical_name,
            language.lanispl,
            language.lanpltrusted,
            language.lanplcallfoid::regprocedure::text,
            CASE WHEN language.laninline = 0 THEN '' ELSE language.laninline::regprocedure::text END,
            CASE WHEN language.lanvalidator = 0 THEN '' ELSE language.lanvalidator::regprocedure::text END,
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(
                            '/',
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                        ),
                        ',' ORDER BY
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                    )
                    FROM aclexplode(language.lanacl) AS privilege
                    LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                    JOIN role_class AS grantor ON grantor.oid = privilege.grantor
                ),
                ''
            )
        )
    FROM extension_member AS member
    JOIN pg_catalog.pg_language AS language
      ON member.classid = 'pg_catalog.pg_language'::regclass
     AND language.oid = member.objid
    JOIN role_class AS owner ON owner.oid = language.lanowner
    UNION ALL
    -- `plpgsql` is an extension member, whereas `c`, `internal`, and `sql`
    -- are stock base languages.  Receipting only extension members lets an
    -- additional database-local procedural language hide until a routine
    -- happens to use it, so bind the full capability inventory as well.
    SELECT
        'language',
        'pg_catalog',
        language.lanname,
        concat_ws(
            ':',
            owner.canonical_name,
            language.lanispl,
            language.lanpltrusted,
            language.lanplcallfoid::regprocedure::text,
            CASE WHEN language.laninline = 0 THEN '' ELSE language.laninline::regprocedure::text END,
            CASE WHEN language.lanvalidator = 0 THEN '' ELSE language.lanvalidator::regprocedure::text END,
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_depend AS language_member
                WHERE language_member.classid = 'pg_catalog.pg_language'::regclass
                  AND language_member.objid = language.oid
                  AND language_member.refclassid = 'pg_catalog.pg_extension'::regclass
                  AND language_member.deptype = 'e'
            ),
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(
                            '/',
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                        ),
                        ',' ORDER BY
                            CASE WHEN privilege.grantee = 0 THEN 'public'
                                 ELSE grantee.canonical_name END,
                            grantor.canonical_name,
                            privilege.privilege_type,
                            privilege.is_grantable
                    )
                    FROM aclexplode(language.lanacl) AS privilege
                    LEFT JOIN role_class AS grantee ON grantee.oid = privilege.grantee
                    JOIN role_class AS grantor ON grantor.oid = privilege.grantor
                ),
                ''
            )
        )
    FROM pg_catalog.pg_language AS language
    JOIN role_class AS owner ON owner.oid = language.lanowner
    UNION ALL
    SELECT
        'extension_member_comment',
        member.extension_schema,
        member.extension_name || ':' ||
            (pg_catalog.pg_identify_object(description.classoid, description.objoid,
                description.objsubid)).identity,
        description.description
    FROM extension_member AS member
    JOIN pg_catalog.pg_description AS description
      ON description.classoid = member.classid
     AND description.objoid = member.objid
    UNION ALL
    SELECT
        'extension_member_security_label',
        member.extension_schema,
        member.extension_name || ':' || security_label.provider || ':' ||
            (pg_catalog.pg_identify_object(security_label.classoid,
                security_label.objoid, security_label.objsubid)).identity,
        security_label.label
    FROM extension_member AS member
    JOIN pg_catalog.pg_seclabel AS security_label
      ON security_label.objoid = member.objid
     AND security_label.classoid = member.classid
    UNION ALL
    SELECT
        'extension_member_unsupported_class',
        member.extension_schema,
        member.extension_name || ':' || member.classid::regclass::text,
        (pg_catalog.pg_identify_object(member.classid, member.objid, 0)).identity
    FROM extension_member AS member
    WHERE member.classid <> ALL (ARRAY[
        'pg_catalog.pg_cast'::regclass,
        'pg_catalog.pg_class'::regclass,
        'pg_catalog.pg_language'::regclass,
        'pg_catalog.pg_opclass'::regclass,
        'pg_catalog.pg_operator'::regclass,
        'pg_catalog.pg_opfamily'::regclass,
        'pg_catalog.pg_proc'::regclass,
        'pg_catalog.pg_type'::regclass
    ])
    UNION ALL
    SELECT
        'namespace',
        namespace.nspname,
        namespace.nspname,
        namespace.nspowner::regrole::text || ':' ||
        COALESCE(
            (
                SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                FROM unnest(namespace.nspacl) AS entry
            ),
            ''
        )
    FROM pg_catalog.pg_namespace AS namespace
    JOIN role_class AS owner ON owner.oid = namespace.nspowner
    -- root baseline은 application schema만 나열해 다른 user schema를 놓치면 안 된다.
    -- pg_*와 information_schema는 PostgreSQL installation-owned namespace라 제외한다.
    WHERE namespace.nspname !~ '^pg_'
      AND namespace.nspname <> 'information_schema'
    UNION ALL
    SELECT
        'default_acl',
        COALESCE(namespace.nspname, '<global>'),
        default_acl.defaclrole::regrole::text || ':' || default_acl.defaclobjtype::text,
        COALESCE(default_acl.defaclacl::text, '')
    FROM pg_catalog.pg_default_acl AS default_acl
    LEFT JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = default_acl.defaclnamespace
    WHERE default_acl.defaclnamespace = 0
       OR (
           namespace.nspname !~ '^pg_'
           AND namespace.nspname <> 'information_schema'
       )
    UNION ALL
    SELECT
        'database',
        '<current>',
        '<current>',
        concat_ws(
            ':',
            database.encoding,
            database.datlocprovider,
            database.datistemplate,
            database.datallowconn,
            database.datconnlimit,
            database.dattablespace,
            database.datcollate,
            database.datctype,
            COALESCE(database.daticulocale, ''),
            COALESCE(database.daticurules, ''),
            COALESCE(database.datcollversion, ''),
            database.datdba::regrole::text,
            COALESCE(database.datacl::text, '')
        )
    FROM pg_catalog.pg_database AS database
    WHERE database.datname = current_database()
    UNION ALL
    SELECT
        'database_setting',
        '<current>',
        '<database>',
        configuration.value
    FROM pg_catalog.pg_db_role_setting AS setting
    CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
    WHERE setting.setdatabase = (
        SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
    )
      AND setting.setrole = 0
    UNION ALL
    SELECT
        'extension',
        namespace.nspname,
        extension.extname,
        concat_ws(
            ':',
            owner.canonical_name,
            extension.extrelocatable,
            extension.extversion,
            COALESCE(
                (
                    SELECT string_agg(
                        concat_ws(chr(30), config_namespace.nspname, config_relation.relname),
                        chr(29) ORDER BY config.ordinality
                    )
                    FROM unnest(extension.extconfig) WITH ORDINALITY
                      AS config(relation_oid, ordinality)
                    JOIN pg_catalog.pg_class AS config_relation
                      ON config_relation.oid = config.relation_oid
                    JOIN pg_catalog.pg_namespace AS config_namespace
                      ON config_namespace.oid = config_relation.relnamespace
                ),
                ''
            ),
            COALESCE(extension.extcondition::text, '')
        )
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
    JOIN role_class AS owner ON owner.oid = extension.extowner
    -- `pg_catalog`도 implicit search_path다. namespace가 아닌 **전체 extension
    -- inventory**를 owner/version/config/condition까지 receipt에 고정한다. extension
    -- member object를 residue에서 제외하더라도 hstore@pg_catalog나 제3 schema extension은
    -- 이 행으로 fingerprint를 바꾸며 metadata stamp 전에 거부된다.
    UNION ALL
    SELECT
        'role',
        '<cluster>',
        role.rolname,
        concat_ws(
            ':',
            role.rolcanlogin,
            role.rolinherit,
            role.rolsuper,
            role.rolcreatedb,
            role.rolcreaterole,
            role.rolbypassrls,
            role.rolreplication,
            role.rolconnlimit,
            COALESCE(role.rolvaliduntil::text, '<null>')
        )
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
    UNION ALL
    SELECT
        'role_setting',
        CASE WHEN setting.setdatabase = 0 THEN '<global>' ELSE '<current>' END,
        CASE WHEN setting.setrole = 0 THEN '<all-roles>' ELSE setting.setrole::regrole::text END,
        configuration.value
    FROM pg_catalog.pg_db_role_setting AS setting
    CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
    WHERE (
        setting.setdatabase = 0
        AND (
            setting.setrole = 0
            OR setting.setrole IN (
                SELECT role.oid
                FROM pg_catalog.pg_roles AS role
                WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
            )
        )
    ) OR (
        setting.setdatabase = (
            SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
        )
        AND setting.setrole IN (
            SELECT role.oid
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
        )
    )
    UNION ALL
    SELECT
        'membership',
        '<cluster>',
        granted.rolname || ':' || member.rolname,
        concat_ws(
            ':',
            membership.admin_option,
            membership.inherit_option,
            membership.set_option
        )
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
    JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
    WHERE granted.rolname LIKE 'ktm\_%' ESCAPE '\'
       OR member.rolname LIKE 'ktm\_%' ESCAPE '\'
    UNION ALL
    SELECT
        'x_extension_usage',
        'x_extension',
        expected.role_name,
        has_schema_privilege(expected.role_name, 'x_extension', 'USAGE')::text
    FROM (
        VALUES
            ('ktm_feature_schema_owner'),
            ('ktm_feature_state_procedure_owner'),
            ('ktm_feature_audit_writer'),
            ('ktm_feature_runtime'),
            ('ktm_curation_command_owner'),
            ('ktm_curation_audit_writer'),
            ('ktm_curation_admin_executor'),
            ('ktm_curation_provider_executor'),
            ('ktm_feature_migrator'),
            ('ktm_feature_api_runtime'),
            ('ktm_feature_dagster_runtime'),
            ('ktm_manual_feature_procedure_owner'),
            ('ktm_manual_feature_admin_executor'),
            ('ktm_feature_create_provider_executor'),
            ('ktm_feature_request_procedure_owner'),
            ('ktm_feature_request_service_executor'),
            ('ktm_feature_request_admin_executor'),
            ('ktm_manual_provider_dedup_procedure_owner'),
            ('ktm_manual_provider_dedup_detector_executor'),
            ('ktm_manual_provider_dedup_admin_executor'),
            ('ktm_feature_reference_reconciliation_service_executor')
    ) AS expected(role_name)
)
SELECT concat_ws(chr(31), kind, schema_name, object_name, definition) AS item
FROM objects
ORDER BY kind, schema_name, object_name, definition;
