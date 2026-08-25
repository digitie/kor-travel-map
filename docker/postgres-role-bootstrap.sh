#!/bin/sh
# T-VN-34A / ADR-090 — dedicated kor-travel-map DB principal bootstrap.
#
# This script deliberately runs only with an explicitly confirmed *dedicated*
# database admin connection.  It is never part of normal API/Dagster startup
# and it never accepts a shared server as an implicit target.
set -eu

# bootstrap superuser DSN과 role password를 가진 process는 caller PATH를 신뢰하지
# 않는다. Manager도 동일 absolute argv/mount를 attest하지만 script 자체가 먼저 닫는다.
PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

require_value() {
  name="$1"
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "$name is required" >&2
    exit 1
  fi
}

require_identifier() {
  name="$1"
  eval "value=\${$name:-}"
  case "$value" in
    [A-Za-z_]* ) ;;
    *)
      echo "$name must be a PostgreSQL identifier" >&2
      exit 1
      ;;
  esac
  case "$value" in
    *[!A-Za-z0-9_]* )
      echo "$name must be a PostgreSQL identifier" >&2
      exit 1
      ;;
  esac
}

if [ "${KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED:-false}" != "true" ]; then
  echo "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED=true is required" >&2
  exit 1
fi
require_value KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN
require_value KOR_TRAVEL_MAP_MIGRATOR_PASSWORD
require_value KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD
require_value KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD
require_identifier KOR_TRAVEL_MAP_POSTGRES_DB
require_identifier KOR_TRAVEL_MAP_POSTGRES_USER

bootstrap_phase="${KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE:-baseline-300}"
case "$bootstrap_phase" in
  baseline-300) ;;
  *)
    echo "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE must be exactly baseline-300" >&2
    exit 1
    ;;
esac

# An operator must repeat the exact target name.  This stops an accidental
# `docker compose up` from transferring ownership on an arbitrary server DB.
if [ "${KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE:-}" \
  != "$KOR_TRAVEL_MAP_POSTGRES_DB" ]; then
  echo "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE must equal KOR_TRAVEL_MAP_POSTGRES_DB" >&2
  exit 1
fi

if [ -r /usr/local/lib/kor-travel-map/database-credential-preflight.sh ]; then
  . /usr/local/lib/kor-travel-map/database-credential-preflight.sh
else
  script_directory="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
  . "$script_directory/../scripts/database-credential-preflight.sh"
fi
validate_map_database_credentials KOR_TRAVEL_MAP_DAGSTER_PG_URL

# Compose healthcheck가 PostgreSQL의 Unix socket을 먼저 확인할 수 있어, 같은
# network에서 오는 첫 TCP connection은 잠시 뒤에야 accept되는 경우가 있다. role
# 변경 전에는 bounded probe로 그 짧은 경합만 흡수하고, 계속 실패하면 fail-closed한다.
bootstrap_probe_attempt=0
until /usr/local/bin/psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT 1' >/dev/null 2>&1; do
  bootstrap_probe_attempt=$((bootstrap_probe_attempt + 1))
  if [ "$bootstrap_probe_attempt" -ge 30 ]; then
    echo "bootstrap DSN did not accept connections within 30 seconds" >&2
    exit 1
  fi
  /usr/bin/sleep 1
done

actual_database="$(/usr/local/bin/psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT current_database()')"
actual_role="$(/usr/local/bin/psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT current_user')"
is_superuser="$(/usr/local/bin/psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')"
if [ "$actual_database" != "$KOR_TRAVEL_MAP_POSTGRES_DB" ]; then
  echo "bootstrap DSN database does not match KOR_TRAVEL_MAP_POSTGRES_DB" >&2
  exit 1
fi
if [ "$actual_role" != "$KOR_TRAVEL_MAP_POSTGRES_USER" ]; then
  echo "bootstrap DSN role does not match KOR_TRAVEL_MAP_POSTGRES_USER" >&2
  exit 1
fi
if [ "$is_superuser" != "t" ]; then
  echo "bootstrap DSN must use the dedicated DB superuser" >&2
  exit 1
fi

run_baseline_300_phase() {
  # `300`은 새 DB용 단일 root다. 기존 0236 DB에는 이 bootstrap을 재실행하지
  # 않는다. 그 전환은 Docker Manager가 소유하는 별도 one-shot handoff만 허용한다.
  /usr/local/bin/psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" \
    --single-transaction \
    -v ON_ERROR_STOP=1 \
    -v migrator_password="$KOR_TRAVEL_MAP_MIGRATOR_PASSWORD" \
    -v api_runtime_password="$KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD" \
    -v dagster_runtime_password="$KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD" <<'SQL'
-- role·membership·database owner/search_path·schema·extension이 한 논리적 fresh
-- bootstrap이다. late membership/extension guard가 실패할 때 앞선 role/password 또는
-- DB setting이 남으면 다음 재시도가 다른 상태를 입력으로 받는다. psql의
-- --single-transaction이 아래 모든 mutation과 guard를 같은 transaction에 묶는다.
DO $baseline_300_fresh_precondition$
BEGIN
    -- baseline-300은 dedicated PostGIS 16 image에서 새로 만든 database만 받는다.
    -- later role/schema normalizer가 임의의 public ACL·extension·default privilege를
    -- 정리하는 repair 도구가 되면 input provenance가 사라진다. 모든 검사는 이
    -- transaction의 첫 mutation 이전에 끝내며, 실패 시 role/password도 남기지 않는다.
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; public.alembic_version exists'
            USING ERRCODE = '55000';
    END IF;

    -- large object는 application schema 밖의 database-wide residue이므로 relation
    -- inventory만 검사하는 fresh guard를 통과해서는 안 된다. root probe의 뒤늦은
    -- 검증까지 role/schema mutation을 진행시키지 않고, 첫 mutation 전에 닫는다.
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_largeobject_metadata) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; large object residue exists'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname NOT IN ('information_schema', 'public')
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; non-system schema exists'
            USING ERRCODE = '55000';
    END IF;

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
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; public schema ACL is not standard'
            USING ERRCODE = '55000';
    END IF;

    -- fresh root가 최종 catalog receipt와 다른 DB 속성에서 시작하면 migration의
    -- 마지막 receipt guard가 거절하더라도 이 bootstrap transaction만 이미 commit된
    -- partial input이 된다. target DB owner와 per-DB setting은 아래 normalizer가
    -- 의도적으로 소유하지만, 그 외 immutable database profile/ACL은 stock template1과
    -- exact해야 한다. PostgreSQL의 ordinary ``CREATE DATABASE``는 template1의 own
    -- ACL을 target에 그대로 복제하지 않고 target ``datacl``을 NULL(default)로
    -- 만든다. 따라서 locale/provider/tablespace/connection-limit는 template1과
    -- 비교하되 target ACL은 canonical fresh NULL로 닫는다.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database AS target_database
        JOIN pg_catalog.pg_database AS template_database
          ON template_database.datname = 'template1'
        WHERE target_database.datname = current_database()
          AND target_database.datistemplate IS FALSE
          AND target_database.encoding = template_database.encoding
          AND target_database.datlocprovider = template_database.datlocprovider
          AND target_database.dattablespace = template_database.dattablespace
          AND target_database.datcollate IS NOT DISTINCT FROM template_database.datcollate
          AND target_database.datctype IS NOT DISTINCT FROM template_database.datctype
          AND target_database.daticulocale IS NOT DISTINCT FROM template_database.daticulocale
          AND target_database.daticurules IS NOT DISTINCT FROM template_database.daticurules
          AND target_database.datcollversion IS NOT DISTINCT FROM template_database.datcollversion
          AND target_database.datallowconn = template_database.datallowconn
          AND target_database.datconnlimit = template_database.datconnlimit
          AND target_database.datacl IS NULL
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; database immutable profile is not standard'
            USING ERRCODE = '55000';
    END IF;

    -- pristine stock PostGIS 16 Alpine database의 input inventory는 plpgsql 하나다.
    -- source `0236`의 fuzzystrmatch는 아래 dedicated bootstrap이 명시적으로 만드는
    -- final contract이지, pre-bootstrap input에 허용할 public residue가 아니다.
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'plpgsql' AND namespace.nspname = 'pg_catalog'
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE NOT (extension.extname = 'plpgsql' AND namespace.nspname = 'pg_catalog')
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; nonstandard extension inventory exists'
            USING ERRCODE = '55000';
    END IF;

    -- procedural language는 relation/extension inventory에 나타나지 않는다. 여기에
    -- foreign language가 있으면 final `300` guard만 뒤늦게 거절해 role/schema가
    -- 남을 수 있으므로, 첫 bootstrap mutation 전에 stock PostgreSQL 16 inventory를
    -- exact하게 닫는다. final root migration의 language contract와 같은 네 언어만
    -- 수용한다.
    IF (
        SELECT COALESCE(
            array_agg(language.lanname::text ORDER BY language.lanname),
            ARRAY[]::text[]
        )
        FROM pg_catalog.pg_language AS language
    ) IS DISTINCT FROM ARRAY['c', 'internal', 'plpgsql', 'sql']::text[] THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; procedural language inventory is not standard'
            USING ERRCODE = '55000';
    END IF;

    -- `pg_prewarm`은 final 300 extension inventory의 필수 구성원이다. image가 이를
    -- 제공하지 않을 때 role·password·schema를 일부 만든 뒤에 실패하면 재시도 입력이
    -- 변하므로, 모든 mutation보다 먼저 availability를 확인한다.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_available_extensions
        WHERE name = 'pg_prewarm'
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires pg_prewarm to be available'
            USING ERRCODE = '55000';
    END IF;

    -- role RESET으로 지워지지 않는 default ACL은 reserved role inventory와 무관하게
    -- fresh input이 아니다. 어느 role/credential/schema mutation보다 먼저 거부한다.
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; default privileges exist'
            USING ERRCODE = '55000';
    END IF;

    -- baseline root는 reserved application role inventory를 exact하게 닫는다. cluster에
    -- 이미 final 21개가 있는 dedicated test/development topology는 재사용할 수 있지만,
    -- partial set 또는 unlisted `ktm_*` NOLOGIN/LOGIN/superuser principal은 repair 대상이
    -- 아니라 잘못된 fresh input이다. 모든 mutation 전에 한 transaction으로 거절한다.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
    ) AND (
        (
            SELECT count(*)
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
        ) <> 21
        OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
              AND role.rolname NOT IN (
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
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires an exact reserved application role inventory'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_db_role_setting AS setting_row
        WHERE setting_row.setdatabase = (
            SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
        ) OR (
            setting_row.setdatabase = 0
            AND (
                setting_row.setrole = 0
                OR setting_row.setrole = current_user::regrole
                OR setting_row.setrole IN (
                    SELECT role.oid
                    FROM pg_catalog.pg_roles AS role
                    WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
                )
            )
        )
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; database or role settings exist'
            USING ERRCODE = '55000';
    END IF;

    -- pre-bootstrap input에는 extension member를 포함한 public object가 하나도 없어야
    -- 한다. final fuzzystrmatch는 이 guard 뒤 dedicated bootstrap이 생성하므로, 여기서
    -- extension-member 예외를 두지 않는다.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.relnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_proc AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.pronamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_type AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.typnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_collation AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.collnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_operator AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.oprnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_cast AS object
        JOIN pg_catalog.pg_type AS source_type ON source_type.oid = object.castsource
        JOIN pg_catalog.pg_type AS target_type ON target_type.oid = object.casttarget
        JOIN pg_catalog.pg_namespace AS source_namespace
          ON source_namespace.oid = source_type.typnamespace
        JOIN pg_catalog.pg_namespace AS target_namespace
          ON target_namespace.oid = target_type.typnamespace
        WHERE (source_namespace.nspname = 'public'
           OR target_namespace.nspname = 'public')
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_config AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.cfgnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_dict AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.dictnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_parser AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.prsnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_ts_template AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.tmplnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_conversion AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.connamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_opfamily AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.opfnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_opclass AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.opcnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_amop AS object
        JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amopfamily
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_amproc AS object
        JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amprocfamily
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_transform AS object
        JOIN pg_catalog.pg_type AS type_row ON type_row.oid = object.trftype
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
        WHERE namespace.nspname = 'public'
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; public objects exist'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_foreign_data_wrapper)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_foreign_server)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_user_mapping)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_publication)
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_subscription AS subscription
           WHERE subscription.subdbid = (
               SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
           )
       )
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; extensibility objects exist'
            USING ERRCODE = '55000';
    END IF;

    -- empty application schemas도 fresh input이 아니다. schema ACL/default ACL은 later
    -- normalizer가 known ktm role만 만지므로, pre-created schema의 foreign principal
    -- 권한을 묵인하면 fresh `300` catalog/authority contract가 깨진다. bootstrap 재실행은
    -- 이미 alembic_version guard가 막으므로, 존재 자체를 mutation 전 atomic reject한다.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; application schemas exist'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.relnamespace
        WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
          AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_proc AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.pronamespace
        WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
        UNION ALL
        SELECT 1
        FROM pg_catalog.pg_type AS object
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = object.typnamespace
        WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
          AND object.typtype IN ('b', 'c', 'd', 'e', 'r')
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; application objects exist'
            USING ERRCODE = '55000';
    END IF;
END
$baseline_300_fresh_precondition$;

DO $baseline_300_roles$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
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
        'ktm_feature_reference_reconciliation_service_executor'
    ] LOOP
        IF to_regrole(role_name) IS NULL THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT', role_name);
        END IF;
        EXECUTE format(
            'ALTER ROLE %I NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
            || 'NOCREATEROLE NOBYPASSRLS NOREPLICATION',
            role_name
        );
        EXECUTE format(
            'ALTER ROLE %I CONNECTION LIMIT -1 VALID UNTIL ''infinity''',
            role_name
        );
        EXECUTE format('ALTER ROLE %I RESET ALL', role_name);
    END LOOP;

    FOREACH role_name IN ARRAY ARRAY[
        'ktm_feature_migrator',
        'ktm_feature_api_runtime',
        'ktm_feature_dagster_runtime'
    ] LOOP
        IF to_regrole(role_name) IS NULL THEN
            EXECUTE format(
                'CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
                || 'NOCREATEROLE NOBYPASSRLS NOREPLICATION',
                role_name
            );
        END IF;
        EXECUTE format(
            'ALTER ROLE %I CONNECTION LIMIT -1 VALID UNTIL ''infinity''',
            role_name
        );
        EXECUTE format('ALTER ROLE %I RESET ALL', role_name);
    END LOOP;
END
$baseline_300_roles$;

-- 신규 prefix role을 role creation/normalization 뒤 다시 exact하게 닫는다. 전 단계의
-- virgin fence와 함께 helper가 enumerated role만 만든다는 두 독립 조건을 제공한다.
DO $baseline_300_role_inventory$
BEGIN
    IF EXISTS (
        WITH expected(rolname) AS (
            VALUES
                ('ktm_curation_admin_executor'),
                ('ktm_curation_audit_writer'),
                ('ktm_curation_command_owner'),
                ('ktm_curation_provider_executor'),
                ('ktm_feature_api_runtime'),
                ('ktm_feature_audit_writer'),
                ('ktm_feature_create_provider_executor'),
                ('ktm_feature_dagster_runtime'),
                ('ktm_feature_migrator'),
                ('ktm_feature_reference_reconciliation_service_executor'),
                ('ktm_feature_request_admin_executor'),
                ('ktm_feature_request_procedure_owner'),
                ('ktm_feature_request_service_executor'),
                ('ktm_feature_runtime'),
                ('ktm_feature_schema_owner'),
                ('ktm_feature_state_procedure_owner'),
                ('ktm_manual_feature_admin_executor'),
                ('ktm_manual_feature_procedure_owner'),
                ('ktm_manual_provider_dedup_admin_executor'),
                ('ktm_manual_provider_dedup_detector_executor'),
                ('ktm_manual_provider_dedup_procedure_owner')
        ),
        actual AS (
            SELECT role.rolname
            FROM pg_catalog.pg_roles AS role
            WHERE role.rolname LIKE 'ktm\_%' ESCAPE '\'
        )
        (SELECT rolname FROM expected EXCEPT SELECT rolname FROM actual)
        UNION ALL
        (SELECT rolname FROM actual EXCEPT SELECT rolname FROM expected)
    ) THEN
        RAISE EXCEPTION 'baseline-300 bootstrap final application role inventory is not exact'
            USING ERRCODE = '42501';
    END IF;
END
$baseline_300_role_inventory$;

SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
    || 'NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_migrator',
    :'migrator_password'
)
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
    || 'NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_api_runtime',
    :'api_runtime_password'
)
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
    || 'NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_dagster_runtime',
    :'dagster_runtime_password'
)
\gexec

-- Existing role principals are cluster-wide. Missing final memberships are
-- provisioned below, but an unexpected edge is never silently removed: it
-- could confer authority in another dedicated database on the same cluster.
DO $baseline_300_membership_precondition$
BEGIN
    IF EXISTS (
        WITH expected(granted_role, member_role, admin_option, inherit_option, set_option) AS (
            VALUES
                ('ktm_curation_admin_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_curation_audit_writer', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_curation_command_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_curation_provider_executor', 'ktm_feature_dagster_runtime', false, true, false),
                ('ktm_feature_audit_writer', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_feature_create_provider_executor', 'ktm_feature_dagster_runtime', false, true, false),
                ('ktm_feature_reference_reconciliation_service_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_feature_request_admin_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_feature_request_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_feature_request_service_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_feature_runtime', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_feature_runtime', 'ktm_feature_dagster_runtime', false, true, false),
                ('ktm_feature_schema_owner', 'ktm_feature_migrator', false, false, true),
                ('ktm_feature_state_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_manual_feature_admin_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_manual_feature_procedure_owner', 'ktm_feature_schema_owner', false, false, true),
                ('ktm_manual_provider_dedup_admin_executor', 'ktm_feature_api_runtime', false, true, false),
                ('ktm_manual_provider_dedup_detector_executor', 'ktm_feature_dagster_runtime', false, true, false),
                ('ktm_manual_provider_dedup_procedure_owner', 'ktm_feature_schema_owner', false, false, true)
        ), actual AS (
            SELECT granted.rolname AS granted_role,
                   member.rolname AS member_role,
                   membership.admin_option,
                   membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
            WHERE granted.rolname IN (
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
                'ktm_feature_reference_reconciliation_service_executor',
                'ktm_feature_migrator', 'ktm_feature_api_runtime',
                'ktm_feature_dagster_runtime'
            ) OR member.rolname IN (
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
                'ktm_feature_reference_reconciliation_service_executor',
                'ktm_feature_migrator', 'ktm_feature_api_runtime',
                'ktm_feature_dagster_runtime'
            )
        )
        SELECT 1 FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) AS unexpected
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap found an unexpected application role membership edge'
            USING ERRCODE = '42501';
    END IF;
END
$baseline_300_membership_precondition$;

GRANT ktm_feature_schema_owner TO ktm_feature_migrator
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_feature_runtime TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_runtime TO ktm_feature_dagster_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_state_procedure_owner TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_feature_audit_writer TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_curation_command_owner TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_curation_audit_writer TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_curation_admin_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_curation_provider_executor TO ktm_feature_dagster_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_manual_feature_procedure_owner TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_manual_feature_admin_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_create_provider_executor TO ktm_feature_dagster_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_request_procedure_owner TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_feature_request_service_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_request_admin_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_manual_provider_dedup_procedure_owner TO ktm_feature_schema_owner
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT ktm_manual_provider_dedup_detector_executor TO ktm_feature_dagster_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_manual_provider_dedup_admin_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
GRANT ktm_feature_reference_reconciliation_service_executor TO ktm_feature_api_runtime
    WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;

CREATE SCHEMA IF NOT EXISTS feature AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS provider_sync AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS x_extension AUTHORIZATION ktm_feature_schema_owner;
ALTER DATABASE :"DBNAME" OWNER TO ktm_feature_schema_owner;
ALTER DATABASE :"DBNAME" RESET ALL;
ALTER DATABASE :"DBNAME" SET search_path TO public, x_extension;
ALTER SCHEMA feature OWNER TO ktm_feature_schema_owner;
ALTER SCHEMA provider_sync OWNER TO ktm_feature_schema_owner;
ALTER SCHEMA ops OWNER TO ktm_feature_schema_owner;
ALTER SCHEMA x_extension OWNER TO ktm_feature_schema_owner;

DO $baseline_300_postgis$
DECLARE
    postgis_schema text;
BEGIN
    SELECT namespace.nspname
      INTO postgis_schema
      FROM pg_catalog.pg_extension AS extension
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
     WHERE extension.extname = 'postgis';
    IF postgis_schema IS NOT NULL AND postgis_schema <> 'x_extension' THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires postgis in x_extension; existing DB repair/drop is unsupported'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
        WHERE extension.extname IN ('pg_trgm', 'pgcrypto', 'pg_prewarm')
          AND namespace.nspname <> 'x_extension'
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires pg_trgm, pgcrypto, and pg_prewarm in x_extension'
            USING ERRCODE = '55000';
    END IF;
END
$baseline_300_postgis$;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA x_extension;
-- exact 0236 source contract에는 legacy fuzzystrmatch가 public에 있다. 이 extension은
-- public 밖으로 relocation하지 않으며, precondition을 통과한 virgin DB에서만 만든다.
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension;

REVOKE ALL ON SCHEMA x_extension FROM PUBLIC;
REVOKE ALL ON SCHEMA x_extension FROM
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_feature_runtime,
    ktm_curation_command_owner,
    ktm_curation_audit_writer,
    ktm_curation_admin_executor,
    ktm_curation_provider_executor,
    ktm_feature_migrator,
    ktm_feature_api_runtime,
    ktm_feature_dagster_runtime,
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
GRANT USAGE ON SCHEMA x_extension TO
    ktm_feature_schema_owner,
    ktm_feature_state_procedure_owner,
    ktm_feature_runtime,
    ktm_feature_api_runtime,
    ktm_feature_dagster_runtime,
    ktm_curation_command_owner,
    ktm_manual_provider_dedup_procedure_owner;

-- sidecar routine ownership is applied by the schema-owner migration. Every
-- possible target owner needs CREATE briefly; `300_schema_baseline.py` removes
-- this bootstrap-only elevation and installs the exact final schema ACL.
REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA feature, provider_sync, ops TO
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_curation_command_owner,
    ktm_curation_audit_writer,
    ktm_manual_feature_procedure_owner,
    ktm_feature_request_procedure_owner,
    ktm_manual_provider_dedup_procedure_owner;
SQL
}

run_baseline_300_phase
echo "kor-travel-map baseline-300 DB role bootstrap completed for $KOR_TRAVEL_MAP_POSTGRES_DB"
