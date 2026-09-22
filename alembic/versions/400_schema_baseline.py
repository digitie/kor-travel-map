"""빈 DB를 head까지 올린 결과를 한 번에 적용하는 단일 root baseline.

Revision ID: 400
Revises: 없음 — 활성 graph의 유일한 root

`300`~`313` 열네 개를 하나로 접었다. 접을 수 있는 이유는 이 저장소가 **운영 중이
아니고**, 따라서 올릴 기존 DB도 보존할 데이터도 없기 때문이다. 그 조건에서
migration 체인은 "과거를 재생할 수 있다"는 성질에 값을 치를 이유가 없고, 체인이
길어질수록 같은 사실(role graph·ACL·procedure 본문)이 여러 revision에 흩어져
서로 어긋날 자리만 늘어난다.

sidecar는 빈 DB를 `313`까지 올린 뒤 `pg_dump`로 뜬 것이다. 사람이 고치는 파일이
아니다 — 고칠 일이 생기면 forward revision을 쌓고, 충분히 쌓이면 다시 접는다.

`300`이 하던 것 중 **빠진 것**:

- sidecar SHA-256 검증과 `application-reference.json` manifest. 0236에서 옮겨 온
  스키마가 손대지 않은 원본인지 증명하기 위한 것이었고, 그 이관은 끝났다.
- catalog/seed **receipt 대조**. 배포된 DB의 카탈로그를 정규화해 해시하고 빌드
  시점 값과 맞추던 검사다. 같은 것을 CI의 ACL·procedure 테스트가 실제 효과로
  재고, 여기서는 봉인된 기대값 파일만 늘렸다.
- 그 receipt 계산 전용이던 canonical contract GUC 9개.

**남은 것**은 전제 확인 둘뿐이고, 둘 다 "이 migration을 돌리면 안 되는 DB"를
가려낸다: role bootstrap이 끝나지 않았거나(role assertion), `public`에 예상 밖의
객체가 있는 경우(catalog assertion). 둘 다 없으면 첫 `ALTER SCHEMA ... OWNER TO`가
읽기 어려운 오류로 터진다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sqlalchemy.util.concurrency import await_only

from alembic import op

# ruff: noqa: E501

revision: str = "400"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASELINE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "baseline"


def _read_sidecar(name: str) -> str:
    return (_BASELINE_DIR / name).read_text(encoding="utf-8")


def _execute_sql_script(sql: str) -> None:
    """asyncpg extended protocol에서도 sidecar의 다중 statement를 같은 transaction에 실행."""

    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


#: bootstrap이 끝난 DB인지 확인한다. role graph의 정본은
#: `docker/postgres-role-bootstrap.sh`이고 이 블록은 그것이 실제로 돌았는지를 잰다.
_ROLE_ASSERTIONS_SQL: Final[str] = r"""
DO $final_application_role_contract$
DECLARE
    observed_extension_inventory text[];
BEGIN
    -- known NOLOGIN/LOGIN checks below와 count를 결합해 reserved `ktm_*`
    -- namespace 전체가 exact 19개임을 보장한다(ADR-100: LOGIN 3 -> 1).
    -- 이 guard가 없으면 unseen prefix
    -- principal이 ownership/ACL catalog boundary 밖에 남을 수 있다.
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname LIKE 'ktm\_%' ESCAPE '\'
    ) <> 19 THEN
        RAISE EXCEPTION '400 baseline requires the exact reserved application role inventory'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_schema_owner', 'ktm_feature_state_procedure_owner',
            'ktm_feature_audit_writer', 'ktm_feature_runtime',
            'ktm_curation_command_owner', 'ktm_curation_audit_writer',
            'ktm_curation_admin_executor', 'ktm_curation_provider_executor',
            'ktm_manual_feature_procedure_owner',
            'ktm_manual_feature_admin_executor',
            'ktm_feature_create_provider_executor',
            'ktm_feature_request_procedure_owner',
            'ktm_feature_request_service_executor',
            'ktm_feature_request_admin_executor',
            'ktm_manual_provider_dedup_procedure_owner',
            'ktm_manual_provider_dedup_detector_executor',
            'ktm_manual_provider_dedup_admin_executor',
            'ktm_feature_reference_reconciliation_service_executor'
        ) AND (
            rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole
            OR rolbypassrls OR rolreplication OR rolconnlimit <> -1
            OR rolvaliduntil IS DISTINCT FROM 'infinity'::timestamptz
        )
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_schema_owner', 'ktm_feature_state_procedure_owner',
            'ktm_feature_audit_writer', 'ktm_feature_runtime',
            'ktm_curation_command_owner', 'ktm_curation_audit_writer',
            'ktm_curation_admin_executor', 'ktm_curation_provider_executor',
            'ktm_manual_feature_procedure_owner',
            'ktm_manual_feature_admin_executor',
            'ktm_feature_create_provider_executor',
            'ktm_feature_request_procedure_owner',
            'ktm_feature_request_service_executor',
            'ktm_feature_request_admin_executor',
            'ktm_manual_provider_dedup_procedure_owner',
            'ktm_manual_provider_dedup_detector_executor',
            'ktm_manual_provider_dedup_admin_executor',
            'ktm_feature_reference_reconciliation_service_executor'
        )
    ) <> 18 THEN
        RAISE EXCEPTION '400 baseline requires all final NOLOGIN application roles'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_service'
        ) AND (
            NOT rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb
            OR rolcreaterole OR rolbypassrls OR rolreplication OR rolconnlimit <> -1
            OR rolvaliduntil IS DISTINCT FROM 'infinity'::timestamptz
        )
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_service'
        )
    ) <> 1 THEN
        RAISE EXCEPTION '400 baseline requires all final LOGIN application roles'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        WITH expected(granted_role, member_role, admin_option, inherit_option, set_option) AS (
            VALUES
                ('ktm_curation_admin_executor', 'ktm_feature_service', false, true, false),
                ('ktm_curation_audit_writer', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_curation_command_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_curation_provider_executor', 'ktm_feature_service', false, true, false),
                ('ktm_feature_audit_writer', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_feature_create_provider_executor', 'ktm_feature_service', false, true, false),
                ('ktm_feature_reference_reconciliation_service_executor', 'ktm_feature_service', false, true, false),
                ('ktm_feature_request_admin_executor', 'ktm_feature_service', false, true, false),
                ('ktm_feature_request_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_feature_request_service_executor', 'ktm_feature_service', false, true, false),
                ('ktm_feature_runtime', 'ktm_feature_service', false, true, false),
                ('ktm_feature_schema_owner', 'ktm_feature_service', false, false, true),
                ('ktm_feature_state_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_manual_feature_admin_executor', 'ktm_feature_service', false, true, false),
                ('ktm_manual_feature_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_manual_provider_dedup_admin_executor', 'ktm_feature_service', false, true, false),
                ('ktm_manual_provider_dedup_detector_executor', 'ktm_feature_service', false, true, false),
                ('ktm_manual_provider_dedup_procedure_owner', 'ktm_feature_schema_owner', false, false, true)
        ),
        actual AS (
            SELECT granted.rolname AS granted_role,
                   member.rolname AS member_role,
                   membership.admin_option,
                   membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
            WHERE granted.rolname LIKE 'ktm\_%' ESCAPE '\'
               OR member.rolname LIKE 'ktm\_%' ESCAPE '\'
        )
        (SELECT * FROM expected EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION '400 baseline application role membership graph is not exact'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database
        WHERE datname = current_database()
          AND datdba = 'ktm_feature_schema_owner'::regrole
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_namespace
        WHERE nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
          AND nspowner = 'ktm_feature_schema_owner'::regrole
    ) <> 4 OR (
        SELECT coalesce(array_agg(setting.value ORDER BY setting.value), ARRAY[]::text[])
        FROM pg_catalog.pg_db_role_setting AS setting_row
        CROSS JOIN LATERAL unnest(setting_row.setconfig) AS setting(value)
        WHERE setting_row.setdatabase = (
            SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
        )
          AND setting_row.setrole = 0
    ) IS DISTINCT FROM ARRAY['search_path=public, x_extension']::text[] OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_db_role_setting AS setting_row
        WHERE (
            setting_row.setdatabase = 0
            AND (
                setting_row.setrole = 0
                OR setting_row.setrole IN (
                    SELECT role.oid
                    FROM pg_catalog.pg_roles AS role
                    WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
                )
            )
        ) OR (
            setting_row.setdatabase = (
                SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
            )
            AND setting_row.setrole IN (
                SELECT role.oid
                FROM pg_catalog.pg_roles AS role
                WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
            )
        )
    ) THEN
        RAISE EXCEPTION '400 baseline requires the final database owner/search_path/role-settings contract'
            USING ERRCODE = '42501';
    END IF;

    SELECT coalesce(
        array_agg(installed.extname || '@' || home.nspname
                  ORDER BY installed.extname::text COLLATE "C",
                           home.nspname::text COLLATE "C"),
        ARRAY[]::text[]
    )
    INTO observed_extension_inventory
    FROM pg_catalog.pg_extension AS installed
    JOIN pg_catalog.pg_namespace AS home ON home.oid = installed.extnamespace;
    IF observed_extension_inventory IS DISTINCT FROM ARRAY[
        'fuzzystrmatch@public',
        'pg_prewarm@x_extension',
        'pg_trgm@x_extension',
        'pgcrypto@x_extension',
        'plpgsql@pg_catalog',
        'postgis@x_extension'
    ]::text[] THEN
        RAISE EXCEPTION '400 baseline requires the exact extension inventory contract'
            USING ERRCODE = '42P01',
                  DETAIL = array_to_string(observed_extension_inventory, ',');
    END IF;

    -- Compose POSTGRES_USER는 deployment마다 달라질 수 있으므로 extension owner
    -- 이름 자체는 immutable catalog receipt에 넣지 않는다. 대신 extension이
    -- application role이 아닌 superuser에게만 속하는지를 fresh transaction에서
    -- fail-close로 증명한다. application schema 네 개의 exact owner는 위
    -- assertion에서 별도로 고정돼 있다.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension AS installed
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = installed.extowner
        WHERE NOT owner.rolsuper
           OR owner.rolname LIKE 'ktm\_%' ESCAPE '\'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace
        WHERE nspname IN ('topology', 'tiger')
    ) THEN
        RAISE EXCEPTION '400 baseline extension bootstrap ownership/inventory contract is not exact'
            USING ERRCODE = '42501';
    END IF;

    -- pg_depend extension member의 owner는 header owner와 별개로 ALTER될 수 있다.
    -- relation/routine/type/operator/operator family·class/language의 owner를 모두
    -- bootstrap-superuser class로 확인한다. ACL의 grantor identity는 catalog receipt에서
    -- 같은 class로 canonicalize하지만 PUBLIC/ktm grant와 grant option은 그대로 hash한다.
    IF EXISTS (
        WITH extension_member AS (
            SELECT dependency.classid, dependency.objid
            FROM pg_catalog.pg_depend AS dependency
            WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
              AND dependency.deptype = 'e'
              AND dependency.objsubid = 0
        ), member_owner AS (
            SELECT member.classid, member.objid, relation.relowner AS owner_oid
            FROM extension_member AS member
            JOIN pg_catalog.pg_class AS relation
              ON member.classid = 'pg_catalog.pg_class'::regclass
             AND relation.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, routine.proowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_proc AS routine
              ON member.classid = 'pg_catalog.pg_proc'::regclass
             AND routine.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, type_row.typowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_type AS type_row
              ON member.classid = 'pg_catalog.pg_type'::regclass
             AND type_row.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, operator_row.oprowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_operator AS operator_row
              ON member.classid = 'pg_catalog.pg_operator'::regclass
             AND operator_row.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, family.opfowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_opfamily AS family
              ON member.classid = 'pg_catalog.pg_opfamily'::regclass
             AND family.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, class.opcowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_opclass AS class
              ON member.classid = 'pg_catalog.pg_opclass'::regclass
             AND class.oid = member.objid
            UNION ALL
            SELECT member.classid, member.objid, language.lanowner
            FROM extension_member AS member
            JOIN pg_catalog.pg_language AS language
              ON member.classid = 'pg_catalog.pg_language'::regclass
             AND language.oid = member.objid
        )
        SELECT 1
        FROM member_owner
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = member_owner.owner_oid
        WHERE NOT owner.rolsuper
           OR owner.rolname LIKE 'ktm\_%' ESCAPE '\'
    ) THEN
        RAISE EXCEPTION '400 baseline extension member ownership contract is not exact'
            USING ERRCODE = '42501';
    END IF;

    -- catalog receipt가 unknown extension member class의 identity만 hash하면 같은 OID의
    -- semantic mutation을 충분히 설명할 수 없다. operator family member의 amop/amproc
    -- child는 receipt가 family를 기준으로 full projection하지만 direct amop/amproc
    -- extension member는 source에 없고 별도 projection도 없으므로 fail-close한다.
    -- 새 class 지원은 receipt projection과 함께 명시적으로 추가한다.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_depend AS dependency
        WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
          AND dependency.deptype = 'e'
          AND dependency.objsubid = 0
          AND dependency.classid <> ALL (ARRAY[
              'pg_catalog.pg_class'::regclass,
              'pg_catalog.pg_proc'::regclass,
              'pg_catalog.pg_type'::regclass,
              'pg_catalog.pg_operator'::regclass,
              'pg_catalog.pg_cast'::regclass,
              'pg_catalog.pg_opfamily'::regclass,
              'pg_catalog.pg_opclass'::regclass,
              'pg_catalog.pg_language'::regclass
          ])
    ) THEN
        RAISE EXCEPTION '400 baseline does not accept unsupported extension member classes'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        WITH expected(role_name, should_have_usage) AS (
            VALUES
                ('ktm_feature_schema_owner', true),
                ('ktm_feature_state_procedure_owner', true),
                ('ktm_feature_audit_writer', false),
                ('ktm_feature_runtime', true),
                ('ktm_curation_command_owner', true),
                ('ktm_curation_audit_writer', false),
                ('ktm_curation_admin_executor', false),
                ('ktm_curation_provider_executor', false),
                ('ktm_feature_service', true),
                ('ktm_manual_feature_procedure_owner', false),
                ('ktm_manual_feature_admin_executor', false),
                ('ktm_feature_create_provider_executor', false),
                ('ktm_feature_request_procedure_owner', false),
                ('ktm_feature_request_service_executor', false),
                ('ktm_feature_request_admin_executor', false),
                ('ktm_manual_provider_dedup_procedure_owner', true),
                ('ktm_manual_provider_dedup_detector_executor', false),
                ('ktm_manual_provider_dedup_admin_executor', false),
                ('ktm_feature_reference_reconciliation_service_executor', false)
        )
        SELECT 1
        FROM expected
        WHERE has_schema_privilege(role_name, 'x_extension', 'USAGE')
              IS DISTINCT FROM should_have_usage
    ) THEN
        RAISE EXCEPTION '400 baseline x_extension USAGE contract is not exact'
            USING ERRCODE = '42501';
    END IF;
END
$final_application_role_contract$;
"""


#: 덤프가 낸 ACL 위에 schema 수준 USAGE/CREATE를 다시 못박는다. pg_dump는 schema
#: ACL을 내지만 PUBLIC REVOKE는 내지 않으므로 여기서 닫는다.
_SCHEMA_PRIVILEGE_NORMALIZATION_SQL: Final[str] = r"""
REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM PUBLIC;
REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_feature_runtime,
    ktm_curation_command_owner,
    ktm_curation_audit_writer,
    ktm_curation_admin_executor,
    ktm_curation_provider_executor,
    ktm_feature_service,
    ktm_manual_feature_procedure_owner,
    ktm_manual_feature_admin_executor,
    ktm_feature_create_provider_executor,
    ktm_feature_request_procedure_owner,
    ktm_feature_request_service_executor,
    ktm_feature_request_admin_executor,
    ktm_manual_provider_dedup_procedure_owner,
    ktm_manual_provider_dedup_detector_executor,
    ktm_manual_provider_dedup_admin_executor,
    ktm_feature_reference_reconciliation_service_executor;

GRANT USAGE, CREATE ON SCHEMA feature TO
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_curation_command_owner,
    ktm_curation_audit_writer,
    ktm_manual_feature_procedure_owner,
    ktm_feature_request_procedure_owner,
    ktm_manual_provider_dedup_procedure_owner;
GRANT USAGE ON SCHEMA feature TO ktm_feature_runtime;

GRANT USAGE ON SCHEMA provider_sync TO
    ktm_feature_runtime,
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_curation_command_owner,
    ktm_manual_provider_dedup_procedure_owner;

GRANT USAGE, CREATE ON SCHEMA ops TO ktm_curation_audit_writer;
GRANT USAGE ON SCHEMA ops TO
    ktm_feature_runtime,
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_curation_command_owner,
    ktm_manual_feature_procedure_owner,
    ktm_feature_request_procedure_owner,
    ktm_manual_provider_dedup_procedure_owner;
"""


#: bootstrap 뒤 `public`에는 fuzzystrmatch extension member와 Alembic version
#: table만 남을 수 있다. 그 밖의 것이 있으면 이 migration이 승인하지 않는다 —
#: 이름만 예외로 두면 extra index/column ACL/RLS/rule/trigger가 stamp의
#: DELETE/INSERT에 개입할 수 있다.
_CATALOG_ASSERTIONS_SQL: Final[str] = r"""
DO $final_application_catalog_contract$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname = 'public'
          AND namespace.nspowner = 'pg_database_owner'::regrole
          AND (
              SELECT COALESCE(
                  array_agg(entry::text ORDER BY entry::text COLLATE "C"),
                  ARRAY[]::text[]
              )
              FROM unnest(namespace.nspacl) AS entry
          ) IS NOT DISTINCT FROM ARRAY[
              '=U/pg_database_owner',
              'pg_database_owner=UC/pg_database_owner'
          ]::text[]
    ) THEN
        RAISE EXCEPTION '400 baseline public schema ACL contract is not exact'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl) THEN
        RAISE EXCEPTION '400 baseline default privilege catalog must be empty'
            USING ERRCODE = '42501';
    END IF;

    -- plpgsql만 extension member로 보아서는 c/internal/sql 이외의 database-local
    -- procedural language가 fresh root와 source receipt 사이에 숨어 버린다.
    -- language object 자체는 restricted migrator도 안전하게 볼 수 있으므로 final
    -- transaction에서 exact stock inventory를 다시 닫는다.
    IF (
        SELECT COALESCE(
            array_agg(language.lanname::text ORDER BY language.lanname),
            ARRAY[]::text[]
        )
        FROM pg_catalog.pg_language AS language
    ) IS DISTINCT FROM ARRAY['c', 'internal', 'plpgsql', 'sql']::text[] THEN
        RAISE EXCEPTION '400 baseline procedural language inventory must be exact'
            USING ERRCODE = '42501';
    END IF;

    -- public에는 Alembic metadata relation 하나만 남는다. 이름만 예외로 두면 extra
    -- index/column ACL/RLS/rule/trigger가 stamp의 DELETE/INSERT에 개입할 수 있으므로,
    -- source와 fresh가 공유하는 canonical table shape를 final transaction에서도
    -- 명시적으로 닫는다. row의 revision 값은 Alembic 자신이 쓴 현재 head이므로 이
    -- structural assertion에는 넣지 않는다.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.relnamespace
        JOIN pg_catalog.pg_am AS table_access_method
          ON table_access_method.oid = object.relam
        WHERE namespace.nspname = 'public'
          AND object.relname = 'alembic_version'
          AND object.relkind = 'r'
          AND object.relowner = 'ktm_feature_schema_owner'::regrole
          AND table_access_method.amname = 'heap'
          AND object.reltablespace = 0
          AND object.relpersistence = 'p'
          AND object.relreplident = 'd'
          AND NOT object.relrowsecurity
          AND NOT object.relforcerowsecurity
          -- production final permit은 API/Dagster runtime login으로 raw ``300``을
          -- 직접 재확인한다. migration metadata를 바꾸는 권한은 주지 않고 shared
          -- runtime role에 version table SELECT 하나만 고정한다.
          AND object.relacl IS NOT NULL
          AND has_table_privilege(
              'ktm_feature_runtime', object.oid, 'SELECT'
          )
          AND NOT has_table_privilege(
              'ktm_feature_runtime', object.oid, 'INSERT, UPDATE, DELETE, '
              || 'TRUNCATE, REFERENCES, TRIGGER'
          )
          AND (
              SELECT count(*)
              FROM aclexplode(object.relacl)
          ) = 8
          AND NOT EXISTS (
              SELECT 1
              FROM aclexplode(object.relacl) AS privilege
              WHERE NOT (
                  (
                      privilege.grantee = object.relowner
                      AND privilege.grantor = object.relowner
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
                      AND privilege.grantor = object.relowner
                      AND privilege.privilege_type = 'SELECT'
                      AND NOT privilege.is_grantable
                  )
              )
          )
          AND object.reloptions IS NULL
          AND object.relnatts = 1
          AND (
              SELECT count(*)
              FROM pg_catalog.pg_type AS row_type
              JOIN pg_catalog.pg_type AS array_type
                ON array_type.oid = row_type.typarray
              WHERE row_type.typrelid = object.oid
                AND row_type.typnamespace = object.relnamespace
                AND row_type.typname = object.relname
                AND row_type.typowner = 'ktm_feature_schema_owner'::regrole
                AND row_type.typtype = 'c'::"char"
                AND row_type.typisdefined
                AND row_type.typcollation = 0
                AND row_type.typacl IS NULL
                AND array_type.typnamespace = object.relnamespace
                AND array_type.typname = '_alembic_version'
                AND array_type.typowner = object.relowner
                AND array_type.typtype = 'b'::"char"
                AND array_type.typcategory = 'A'::"char"
                AND array_type.typisdefined
                AND array_type.typcollation = 0
                AND array_type.typacl IS NULL
                AND array_type.typrelid = 0
                AND array_type.typarray = 0
                AND array_type.typelem = row_type.oid
          ) = 1
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS extension_member
              WHERE extension_member.classid = 'pg_catalog.pg_class'::regclass
                AND extension_member.objid = object.oid
                AND extension_member.refclassid = 'pg_catalog.pg_extension'::regclass
                AND extension_member.deptype = 'e'
          )
          AND (
              SELECT count(*)
              FROM pg_catalog.pg_attribute AS attribute
              WHERE attribute.attrelid = object.oid
                AND attribute.attnum > 0
                AND NOT attribute.attisdropped
          ) = 1
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_attribute AS attribute
              WHERE attribute.attrelid = object.oid
                AND attribute.attnum > 0
                AND attribute.attisdropped
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_attribute AS attribute
              WHERE attribute.attrelid = object.oid
                AND attribute.attnum > 0
                AND NOT attribute.attisdropped
                AND (
                    attribute.attnum <> 1
                    OR attribute.attname <> 'version_num'
                    OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                        <> 'character varying(32)'
                    OR NOT attribute.attnotnull
                    OR attribute.atthasdef
                    OR attribute.attidentity <> ''::"char"
                    OR attribute.attgenerated <> ''::"char"
                    OR attribute.attndims <> 0
                    OR attribute.attstattarget <> -1
                    OR attribute.attstorage <> 'x'::"char"
                    OR attribute.attcompression <> ''::"char"
                    OR attribute.attacl IS NOT NULL
                    OR attribute.attoptions IS NOT NULL
                    OR attribute.attfdwoptions IS NOT NULL
                )
          )
          AND (
              SELECT count(*)
              FROM pg_catalog.pg_constraint AS constraint_row
              WHERE constraint_row.conrelid = object.oid
          ) = 1
          AND EXISTS (
              SELECT 1
              FROM pg_catalog.pg_constraint AS constraint_row
              WHERE constraint_row.conrelid = object.oid
                AND constraint_row.conname = 'alembic_version_pkc'
                AND constraint_row.contype = 'p'::"char"
                AND NOT constraint_row.condeferrable
                AND NOT constraint_row.condeferred
                AND constraint_row.convalidated
                AND constraint_row.conislocal
                AND constraint_row.coninhcount = 0
                AND constraint_row.connoinherit
                AND constraint_row.conkey = ARRAY[1]::smallint[]
                AND pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
                    = 'PRIMARY KEY (version_num)'
          )
          AND (
              SELECT count(*)
              FROM pg_catalog.pg_index AS index_row
              WHERE index_row.indrelid = object.oid
          ) = 1
          AND EXISTS (
              SELECT 1
              FROM pg_catalog.pg_index AS index_row
              JOIN pg_catalog.pg_class AS index_relation
                ON index_relation.oid = index_row.indexrelid
              JOIN pg_catalog.pg_am AS index_access_method
                ON index_access_method.oid = index_relation.relam
              WHERE index_row.indrelid = object.oid
                AND index_relation.relname = 'alembic_version_pkc'
                AND index_relation.relkind = 'i'
                AND index_relation.relowner = 'ktm_feature_schema_owner'::regrole
                AND index_relation.relacl IS NULL
                AND index_relation.reloptions IS NULL
                AND index_access_method.amname = 'btree'
                AND index_relation.reltablespace = 0
                AND index_row.indisunique
                AND NOT index_row.indnullsnotdistinct
                AND index_row.indisprimary
                AND NOT index_row.indisexclusion
                AND index_row.indimmediate
                AND NOT index_row.indisclustered
                AND index_row.indisvalid
                AND NOT index_row.indcheckxmin
                AND index_row.indisready
                AND index_row.indislive
                AND NOT index_row.indisreplident
                AND index_row.indnkeyatts = 1
                AND index_row.indnatts = 1
                AND index_row.indkey::text = '1'
                AND index_row.indpred IS NULL
                AND index_row.indexprs IS NULL
                AND pg_catalog.pg_get_indexdef(index_row.indexrelid)
                    = 'CREATE UNIQUE INDEX alembic_version_pkc '
                      || 'ON public.alembic_version USING btree (version_num)'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_trigger AS trigger
              WHERE trigger.tgrelid = object.oid
                AND NOT trigger.tgisinternal
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_rewrite AS rule
              WHERE rule.ev_class = object.oid
                AND rule.rulename <> '_RETURN'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_policy AS policy
              WHERE policy.polrelid = object.oid
          )
    ) THEN
        RAISE EXCEPTION '400 baseline public.alembic_version contract is not exact'
            USING ERRCODE = '42501';
    END IF;

    -- publication/subscription은 fresh root와 metadata-only handoff가 재현하지 않는
    -- 외부 replication topology다. subscription connection option은 restricted role이
    -- 읽을 수 있는 catalog가 아니므로 digest에 넣어 평문/권한 경계를 넓히지 않는다.
    -- publication은 현재 DB 고유 catalog이고 subscription은 cluster-shared catalog지만
    -- `subdbid`가 owning DB를 가리킨다. 따라서 Map database policy는 current DB의
    -- subscription만 zero여야 하며, 다른 dedicated DB의 topology를 이 migration이
    -- 승인/거부하지 않는다. Manager privileged receipt도 같은 scope를 증명한다.
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_publication)
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_subscription AS subscription
           WHERE subscription.subdbid = (
               SELECT oid FROM pg_catalog.pg_database
               WHERE datname = current_database()
           )
       ) THEN
        RAISE EXCEPTION '400 baseline replication topology must be empty'
            USING ERRCODE = '42501';
    END IF;

    -- final extension inventory is exact above. public에는 그 contract의
    -- fuzzystrmatch extension member와 Alembic version table만 남길 수 있다.
    -- extension member CTE는 이 single statement에만 쓰므로 precondition/final guard
    -- 사이에서 catalog alias 또는 CTE scope가 새지 않는다.
    IF EXISTS (
        WITH extension_member AS (
            SELECT dependency.classid, dependency.objid
            FROM pg_catalog.pg_depend AS dependency
            WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
              AND dependency.deptype = 'e'
              AND dependency.objsubid = 0
        )
        SELECT 1
        FROM pg_catalog.pg_class AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.relnamespace
        WHERE namespace.nspname = 'public'
          AND object.relkind <> 'i'
          AND NOT (object.relkind = 'r' AND object.relname = 'alembic_version')
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_class'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_proc AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.pronamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_proc'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_type AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.typnamespace
        WHERE namespace.nspname = 'public'
          AND object.typrelid = 0
          AND object.typelem = 0
          AND object.typisdefined
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_type'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_collation AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.collnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_collation'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_operator AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.oprnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_operator'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_cast AS object
        JOIN pg_catalog.pg_type AS source_type ON source_type.oid = object.castsource
        JOIN pg_catalog.pg_type AS target_type ON target_type.oid = object.casttarget
        JOIN pg_catalog.pg_namespace AS source_namespace
          ON source_namespace.oid = source_type.typnamespace
        JOIN pg_catalog.pg_namespace AS target_namespace
          ON target_namespace.oid = target_type.typnamespace
        WHERE (source_namespace.nspname = 'public' OR target_namespace.nspname = 'public')
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_cast'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_conversion AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.connamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_conversion'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_opfamily AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.opfnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_opfamily'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_opclass AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.opcnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_opclass'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_amop AS object
        JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amopfamily
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_opfamily'::regclass
                AND member.objid = family.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_amproc AS object
        JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amprocfamily
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_opfamily'::regclass
                AND member.objid = family.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_config AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.cfgnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_ts_config'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_config_map AS mapping
        JOIN pg_catalog.pg_ts_config AS configuration ON configuration.oid = mapping.mapcfg
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_ts_config'::regclass
                AND member.objid = configuration.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_dict AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.dictnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_ts_dict'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_parser AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.prsnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_ts_parser'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_template AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.tmplnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_ts_template'::regclass
                AND member.objid = object.oid
          )
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_transform AS object
        JOIN pg_catalog.pg_type AS type_row ON type_row.oid = object.trftype
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
        WHERE namespace.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1
              FROM extension_member AS member
              WHERE member.classid = 'pg_catalog.pg_transform'::regclass
                AND member.objid = object.oid
          )
    ) THEN
        RAISE EXCEPTION '400 baseline public residue catalog is not empty'
            USING ERRCODE = '42501';
    END IF;
END
$final_application_catalog_contract$;
"""


#: seed가 아니라 런타임 투영의 초기값이다. 덤프에 담지 않는 이유는 이 두 표가
#: 데이터가 아니라 카운터이기 때문이다 — ON CONFLICT DO NOTHING으로 멱등하다.
_RUNTIME_PROJECTION_INITIALIZATION_SQL: Final[str] = r"""
INSERT INTO ops.import_job_event_clock (clock_id, revision, updated_at)
VALUES (true, 0, clock_timestamp())
ON CONFLICT (clock_id) DO NOTHING;

INSERT INTO ops.ops_live_topic_revisions (topic, revision, updated_at)
VALUES
    ('dagster_schedules', 0, clock_timestamp()),
    ('dataset_projection', 0, clock_timestamp()),
    ('provider_sync', 0, clock_timestamp())
ON CONFLICT (topic) DO NOTHING;
"""


def upgrade() -> None:
    """bootstrap이 끝난 fresh DB에 head 덤프를 적용한다."""

    op.execute(_ROLE_ASSERTIONS_SQL)
    _execute_sql_script(_read_sidecar("schema.sql"))
    _execute_sql_script(_SCHEMA_PRIVILEGE_NORMALIZATION_SQL)
    _execute_sql_script(_read_sidecar("seed.sql"))
    _execute_sql_script(_RUNTIME_PROJECTION_INITIALIZATION_SQL)
    op.execute("GRANT SELECT ON TABLE public.alembic_version TO ktm_feature_runtime")
    op.execute(_CATALOG_ASSERTIONS_SQL)


def downgrade() -> None:
    """되돌리지 않는다.

    이 저장소는 운영 중이 아니고 데이터 보존도 요구하지 않는다. 되돌릴 일이
    생기면 downgrade가 아니라 forward revision으로 하거나 DB를 새로 만든다.
    되돌릴 수 없는데 조용히 성공한 척하는 것이 가장 나쁘므로 거부한다.
    """

    raise RuntimeError("400_schema_baseline is forward-only")
