-- `0236 → 300` handoff와 fresh `300` baseline이 함께 쓰는 불변 application
-- catalog receipt. 각 행은 `kind`, `schema_name`, `object_name`, `definition`의
-- 결정론적 표현이며, 호출자는 UTF-8 행 + LF를 SHA-256 한다.
--
-- 이 파일은 `scripts/run-admin-feature-clone-live-acceptance.sh`의 schema/database/
-- extension receipt와 같은 catalog 축을 한 query로 묶는다. `300` handoff는 raw
-- `alembic_version`만 stamp할 수 있으므로, source와 destination 모두 이 receipt가
-- immutable reference hash와 같아야 한다.
WITH objects AS (
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
        COALESCE(attribute.attacl::text, '') || ':' ||
        COALESCE(pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid), '') || ':' ||
        attribute.attstattarget::text || ':' ||
        COALESCE(
            (SELECT string_agg(option, ',' ORDER BY option)
             FROM unnest(attribute.attoptions) AS option),
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
    SELECT
        'relation', namespace.nspname, relation.relname,
        concat_ws(
            ':',
            relation.relkind,
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
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
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
        'public_residue_user_mapping',
        '<cluster>',
        server.srvname || ':' || CASE
            WHEN mapping.umuser = 0 THEN 'public'
            ELSE mapping.umuser::regrole::text
        END,
        wrapper.fdwname
    -- `pg_user_mapping` base catalog은 schema owner에게 SELECT를 주지 않아 handoff
    -- preflight가 credential metadata를 읽을 수 없다. privilege-filtered public view는
    -- mapping identity만 제공하고 `umoptions`는 권한이 없으면 NULL로 숨기므로, secret을
    -- receipt에 넣지 않으면서 foreign mapping의 존재/대상 role은 still fail-close한다.
    FROM pg_catalog.pg_user_mappings AS mapping
    JOIN pg_catalog.pg_foreign_server AS server ON server.oid = mapping.srvid
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
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync', 'x_extension', 'public')
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
       OR namespace.nspname IN ('feature', 'ops', 'provider_sync', 'x_extension')
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
            extension.extowner::regrole::text,
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
    -- application contract는 실제 application이 의존하는 확장 세 개만 고정한다.
    -- pg_prewarm 등 서버/image 운영 옵션과 자동 설치된 contrib extension을 전역 catalog
    -- identity에 섞으면 fresh DB와 정상 운영 DB를 거짓으로 다르게 판정한다.
    WHERE extension.extname IN ('postgis', 'pgcrypto', 'pg_trgm')
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
    WHERE role.rolname IN (
        'ktm_feature_schema_owner',
        'ktm_feature_state_procedure_owner',
        'ktm_feature_audit_writer',
        'ktm_feature_runtime',
        'ktm_curation_command_owner',
        'ktm_curation_audit_writer',
        'ktm_curation_admin_executor',
        'ktm_curation_provider_executor',
        'ktm_manual_feature_procedure_owner',
        'ktm_manual_feature_admin_executor',
        'ktm_feature_create_provider_executor',
        'ktm_feature_request_procedure_owner',
        'ktm_feature_request_service_executor',
        'ktm_feature_request_admin_executor',
        'ktm_manual_provider_dedup_procedure_owner',
        'ktm_manual_provider_dedup_detector_executor',
        'ktm_manual_provider_dedup_admin_executor',
        'ktm_feature_reference_reconciliation_service_executor',
        'ktm_feature_migrator',
        'ktm_feature_api_runtime',
        'ktm_feature_dagster_runtime'
    )
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
                WHERE role.rolname IN (
                    'ktm_feature_schema_owner',
                    'ktm_feature_state_procedure_owner',
                    'ktm_feature_audit_writer',
                    'ktm_feature_runtime',
                    'ktm_curation_command_owner',
                    'ktm_curation_audit_writer',
                    'ktm_curation_admin_executor',
                    'ktm_curation_provider_executor',
                    'ktm_manual_feature_procedure_owner',
                    'ktm_manual_feature_admin_executor',
                    'ktm_feature_create_provider_executor',
                    'ktm_feature_request_procedure_owner',
                    'ktm_feature_request_service_executor',
                    'ktm_feature_request_admin_executor',
                    'ktm_manual_provider_dedup_procedure_owner',
                    'ktm_manual_provider_dedup_detector_executor',
                    'ktm_manual_provider_dedup_admin_executor',
                    'ktm_feature_reference_reconciliation_service_executor',
                    'ktm_feature_migrator',
                    'ktm_feature_api_runtime',
                    'ktm_feature_dagster_runtime'
                )
            )
        )
    ) OR (
        setting.setdatabase = (
            SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
        )
        AND setting.setrole IN (
            SELECT role.oid
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname IN (
                'ktm_feature_schema_owner',
                'ktm_feature_state_procedure_owner',
                'ktm_feature_audit_writer',
                'ktm_feature_runtime',
                'ktm_curation_command_owner',
                'ktm_curation_audit_writer',
                'ktm_curation_admin_executor',
                'ktm_curation_provider_executor',
                'ktm_manual_feature_procedure_owner',
                'ktm_manual_feature_admin_executor',
                'ktm_feature_create_provider_executor',
                'ktm_feature_request_procedure_owner',
                'ktm_feature_request_service_executor',
                'ktm_feature_request_admin_executor',
                'ktm_manual_provider_dedup_procedure_owner',
                'ktm_manual_provider_dedup_detector_executor',
                'ktm_manual_provider_dedup_admin_executor',
                'ktm_feature_reference_reconciliation_service_executor',
                'ktm_feature_migrator',
                'ktm_feature_api_runtime',
                'ktm_feature_dagster_runtime'
            )
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
