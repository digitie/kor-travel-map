#!/usr/bin/env sh
# T-VN-34A / ADR-090 — dedicated kor-travel-map DB principal bootstrap.
#
# This script deliberately runs only with an explicitly confirmed *dedicated*
# database admin connection.  It is never part of normal API/Dagster startup
# and it never accepts a shared server as an implicit target.
set -eu

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

# Compose healthcheck가 PostgreSQL의 Unix socket을 먼저 확인할 수 있어, 같은
# network에서 오는 첫 TCP connection은 잠시 뒤에야 accept되는 경우가 있다. role
# 변경 전에는 bounded probe로 그 짧은 경합만 흡수하고, 계속 실패하면 fail-closed한다.
bootstrap_probe_attempt=0
until psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT 1' >/dev/null 2>&1; do
  bootstrap_probe_attempt=$((bootstrap_probe_attempt + 1))
  if [ "$bootstrap_probe_attempt" -ge 30 ]; then
    echo "bootstrap DSN did not accept connections within 30 seconds" >&2
    exit 1
  fi
  sleep 1
done

actual_database="$(psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT current_database()')"
actual_role="$(psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT current_user')"
is_superuser="$(psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" -Atqc 'SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')"
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
  psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" \
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
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires a fresh DB; public.alembic_version exists'
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
        WHERE extension.extname IN ('pg_trgm', 'pgcrypto')
          AND namespace.nspname <> 'x_extension'
    ) THEN
        RAISE EXCEPTION
            'baseline-300 bootstrap requires pg_trgm and pgcrypto in x_extension'
            USING ERRCODE = '55000';
    END IF;
END
$baseline_300_postgis$;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA x_extension;
DO $baseline_300_prewarm$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_available_extensions WHERE name = 'pg_prewarm') THEN
        CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension;
    END IF;
END
$baseline_300_prewarm$;

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
    ktm_feature_state_procedure_owner,
    ktm_feature_runtime,
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
