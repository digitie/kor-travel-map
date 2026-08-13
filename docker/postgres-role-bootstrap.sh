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

# An operator must repeat the exact target name.  This stops an accidental
# `docker compose up` from transferring ownership on an arbitrary server DB.
if [ "${KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE:-}" \
  != "$KOR_TRAVEL_MAP_POSTGRES_DB" ]; then
  echo "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE must equal KOR_TRAVEL_MAP_POSTGRES_DB" >&2
  exit 1
fi

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

# psql variables keep passwords out of SQL source and repo files.  PostgreSQL
# stores only its password verifier; Alembic revisions never create a LOGIN or
# password.
psql "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" \
  -v ON_ERROR_STOP=1 \
  -v bootstrap_role="$KOR_TRAVEL_MAP_POSTGRES_USER" \
  -v migrator_password="$KOR_TRAVEL_MAP_MIGRATOR_PASSWORD" \
  -v api_runtime_password="$KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD" \
  -v dagster_runtime_password="$KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD" <<'SQL'
DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_schema_owner') THEN
        CREATE ROLE ktm_feature_schema_owner NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner') THEN
        CREATE ROLE ktm_feature_state_procedure_owner NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer') THEN
        CREATE ROLE ktm_feature_audit_writer NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime') THEN
        CREATE ROLE ktm_feature_runtime NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_curation_command_owner') THEN
        CREATE ROLE ktm_curation_command_owner NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_curation_audit_writer') THEN
        CREATE ROLE ktm_curation_audit_writer NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_curation_admin_executor') THEN
        CREATE ROLE ktm_curation_admin_executor NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_curation_provider_executor') THEN
        CREATE ROLE ktm_curation_provider_executor NOLOGIN NOINHERIT;
    END IF;
END
$roles$;

ALTER ROLE ktm_curation_command_owner NOLOGIN NOINHERIT
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
ALTER ROLE ktm_curation_audit_writer NOLOGIN NOINHERIT
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
ALTER ROLE ktm_curation_admin_executor NOLOGIN NOINHERIT
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
ALTER ROLE ktm_curation_provider_executor NOLOGIN NOINHERIT
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;

-- ``ktm_feature_migrator``는 superuser가 아니다. PostgreSQL 16/PostGIS extension
-- 설치와 application schema 준비는 dedicated bootstrap connection에서만 한다.
-- fresh postgis image가 public에 자동 설치한 non-relocatable extension은 relocation을
-- 지원하지 않는다. application relation이 하나도 없는 fresh DB에서만 다시 만들 수 있고,
-- populated DB가 그런 상태면 destructive drop 없이 fail-closed 한다.
CREATE SCHEMA IF NOT EXISTS feature AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS provider_sync AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION ktm_feature_schema_owner;
CREATE SCHEMA IF NOT EXISTS x_extension AUTHORIZATION ktm_feature_schema_owner;
DO $postgis_schema$
DECLARE
    v_postgis_schema text;
    v_has_application_relation boolean;
BEGIN
    SELECT n.nspname
      INTO v_postgis_schema
      FROM pg_catalog.pg_extension AS e
      JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
     WHERE e.extname = 'postgis';
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('feature', 'provider_sync', 'ops')
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    ) INTO v_has_application_relation;
    IF v_postgis_schema IS NOT NULL
       AND v_postgis_schema <> 'x_extension' THEN
        IF v_has_application_relation THEN
            RAISE EXCEPTION
                'bootstrap refuses to replace postgis in schema % on a populated application DB',
                v_postgis_schema
                USING ERRCODE = '55000',
                      HINT = 'Move/rebuild the extension during a dedicated maintenance migration before role bootstrap.';
        END IF;
        EXECUTE 'DROP EXTENSION IF EXISTS postgis_topology CASCADE';
        EXECUTE 'DROP EXTENSION postgis CASCADE';
    END IF;
END
$postgis_schema$;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA x_extension;

-- T-102 pg_prewarm. migration ``0022_pg_prewarm_extension``은 "current_user가
-- superuser일 때만 만든다"로 짜였는데, ADR-090 이후 alembic은 NOSUPERUSER
-- ``ktm_feature_migrator``로만 돈다 — 그 분기는 이제 영구히 no-op이라 확장이 어디서도
-- 생기지 않았다. pg_prewarm은 trusted extension이 아니어서 schema owner 권한으로도
-- 만들 수 없고, 남은 유일한 설치 지점이 이 dedicated superuser connection이다.
-- 다만 T-102는 opt-in/best-effort이고 외부 관리형 Postgres에는 contrib이 없을 수 있으므로
-- available할 때만 만든다. 없으면 ``kortravelmap.infra.prewarm``이 no-op으로 degrade한다.
DO $pg_prewarm$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_available_extensions WHERE name = 'pg_prewarm') THEN
        CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension;
    END IF;
END
$pg_prewarm$;

SELECT format(
    'CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION',
    'ktm_feature_migrator'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_migrator')
\gexec
SELECT format(
    'CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION',
    'ktm_feature_api_runtime'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_api_runtime')
\gexec
SELECT format(
    'CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION',
    'ktm_feature_dagster_runtime'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_dagster_runtime')
\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_migrator',
    :'migrator_password'
)
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_api_runtime',
    :'api_runtime_password'
)
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION PASSWORD %L',
    'ktm_feature_dagster_runtime',
    :'dagster_runtime_password'
)
\gexec

-- PostgreSQL 16 membership options are part of the trust boundary: runtime
-- principals inherit table/procedure grants but may not SET ROLE into groups.
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
-- 0095 transfers SECURITY DEFINER routines to these NOLOGIN owners. PostgreSQL
-- requires the target owner to hold CREATE on the containing schema during
-- ``ALTER FUNCTION/PROCEDURE ... OWNER``; neither role can authenticate and
-- runtime memberships never allow SET ROLE into either owner group.
GRANT USAGE, CREATE ON SCHEMA feature
    TO ktm_feature_state_procedure_owner, ktm_feature_audit_writer,
       ktm_curation_command_owner, ktm_curation_audit_writer;
GRANT USAGE, CREATE ON SCHEMA ops TO ktm_curation_audit_writer;

DO $assert_roles$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_curation_command_owner', 'ktm_curation_audit_writer',
            'ktm_curation_admin_executor', 'ktm_curation_provider_executor'
        )
          AND (rolcanlogin OR rolinherit OR rolsuper OR rolcreaterole OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'curation NOLOGIN role has an unsafe role attribute';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname IN ('ktm_feature_api_runtime', 'ktm_feature_dagster_runtime')
          AND (NOT rolcanlogin OR rolsuper OR rolcreaterole OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'runtime login has an unsafe role attribute';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname = 'ktm_feature_migrator'
          AND (NOT rolcanlogin OR rolsuper OR rolcreaterole OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'migrator login has an unsafe role attribute';
    END IF;
    IF pg_has_role('ktm_feature_api_runtime', 'ktm_feature_schema_owner', 'member')
       OR pg_has_role('ktm_feature_dagster_runtime', 'ktm_feature_schema_owner', 'member') THEN
        RAISE EXCEPTION 'runtime login must not belong to ktm_feature_schema_owner';
    END IF;
    IF NOT pg_has_role('ktm_feature_api_runtime', 'ktm_curation_admin_executor', 'member')
       OR pg_has_role('ktm_feature_api_runtime', 'ktm_curation_provider_executor', 'member')
       OR NOT pg_has_role('ktm_feature_dagster_runtime', 'ktm_curation_provider_executor', 'member')
       OR pg_has_role('ktm_feature_dagster_runtime', 'ktm_curation_admin_executor', 'member') THEN
        RAISE EXCEPTION 'curation executor membership is unsafe';
    END IF;
END
$assert_roles$;

-- ``REASSIGN OWNED BY`` cannot be used for the initial PostgreSQL superuser:
-- it owns required pg_catalog/information_schema objects. Transfer *only* the
-- application DB/object namespace instead, never cluster-wide system ownership.
-- This script is never enabled by external/shared compose overlays.
ALTER DATABASE :"DBNAME" OWNER TO ktm_feature_schema_owner;

SELECT format('ALTER SCHEMA %I OWNER TO ktm_feature_schema_owner', nspname)
FROM pg_catalog.pg_namespace
WHERE nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
\gexec

SELECT format(
    'ALTER %s %I.%I OWNER TO ktm_feature_schema_owner',
    CASE relkind
        WHEN 'r' THEN 'TABLE'
        WHEN 'p' THEN 'TABLE'
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        WHEN 'S' THEN 'SEQUENCE'
        WHEN 'f' THEN 'FOREIGN TABLE'
    END,
    nspname,
    relname
)
FROM pg_catalog.pg_class
JOIN pg_catalog.pg_namespace ON pg_namespace.oid = pg_class.relnamespace
WHERE nspname IN ('feature', 'provider_sync', 'ops')
  AND relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  -- identity/serial로 테이블 컬럼에 묶인 시퀀스는 **제외한다.** PostgreSQL은 그런
  -- 시퀀스의 소유자 변경을 거부한다("cannot change owner of sequence ... linked to
  -- table") — 소유권이 소유 테이블을 따라가기 때문이다. 그래서 데이터가 있는 DB에서는
  -- 이 sweep이 ON_ERROR_STOP으로 죽고 소유권이 **절반만 이전된** 상태로 남아,
  -- 재실행해도 같은 지점에서 다시 죽는다(2026-08-13 prod 리허설 실측: exit 3,
  -- 82개 중 10개만 이전). fresh DB에서는 대상이 0개라 이 결함이 드러나지 않는다.
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend
      WHERE pg_depend.classid = 'pg_class'::regclass
        AND pg_depend.objid = pg_class.oid
        AND pg_depend.deptype IN ('a', 'i')
  )
\gexec

-- ``public.alembic_version``도 넘긴다. 위 sweep은 application schema만 훑고
-- ``ALTER DATABASE ... OWNER``는 테이블 소유자를 바꾸지 않으므로, 기존 DB에서는 이
-- 테이블이 구 bootstrap superuser 소유로 남는다. 그러면 ADR-090 경로(migrator LOGIN →
-- ``SET ROLE ktm_feature_schema_owner``)가 첫 ``SELECT version_num``에서
-- ``permission denied for table alembic_version``으로 죽어 **단 한 revision도**
-- 적용되지 못한다. fresh DB에서는 alembic이 schema owner 자격으로 직접 만들기 때문에
-- 하네스 전량에서 무증상이었다.
SELECT format('ALTER TABLE public.%I OWNER TO ktm_feature_schema_owner', relname)
FROM pg_catalog.pg_class
JOIN pg_catalog.pg_namespace ON pg_namespace.oid = pg_class.relnamespace
WHERE nspname = 'public'
  AND relname = 'alembic_version'
  AND relkind = 'r'
\gexec

SELECT format(
    'ALTER %s %I.%I(%s) OWNER TO ktm_feature_schema_owner',
    CASE prokind
        WHEN 'p' THEN 'PROCEDURE'
        WHEN 'a' THEN 'AGGREGATE'
        ELSE 'FUNCTION'
    END,
    nspname,
    proname,
    pg_get_function_identity_arguments(pg_proc.oid)
)
FROM pg_catalog.pg_proc
JOIN pg_catalog.pg_namespace ON pg_namespace.oid = pg_proc.pronamespace
WHERE nspname IN ('feature', 'provider_sync', 'ops')
  AND pg_get_userbyid(pg_proc.proowner) NOT IN (
      'ktm_feature_state_procedure_owner', 'ktm_feature_audit_writer',
      'ktm_curation_command_owner', 'ktm_curation_audit_writer'
  )
\gexec

-- Older bootstrap versions transferred every routine back to the schema
-- owner.  Repair the closed SECURITY DEFINER manifest after the ordinary
-- ownership sweep; missing routines (for an earlier migration head) are
-- ignored and will be created by Alembic with the same owner later.
WITH dedicated_routine(signature, owner_role) AS (
    VALUES
      ('feature.prepare_feature_state_context(jsonb,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)', 'ktm_feature_state_procedure_owner'),
      ('feature.transition_feature_state(text,text,text,text,bigint,jsonb)', 'ktm_feature_state_procedure_owner'),
      ('feature.lock_current_provider_source_evidence(bigint,text,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.lock_current_provider_feature_source_evidence(text,bigint,text,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.transition_admin_feature_state(text,text,text,text,bigint,text,text,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.reactivate_admin_feature_state(text,bigint,text,text,bigint,text,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.author_lifecycle_override(text,text,text,boolean,text,text,bigint)', 'ktm_feature_state_procedure_owner'),
      ('feature.revoke_lifecycle_override(text,text,bigint)', 'ktm_feature_state_procedure_owner'),
      ('feature.has_active_feature_override(text,text)', 'ktm_feature_state_procedure_owner'),
      ('feature.apply_provider_feature_field_patch(text,bigint,text,text,bigint,jsonb,jsonb)', 'ktm_feature_state_procedure_owner'),
      ('feature.author_feature_field_overrides(text,bigint,text,text,bigint,jsonb,jsonb)', 'ktm_feature_state_procedure_owner'),
      ('feature.revoke_feature_field_overrides(text,bigint,text,text,bigint,text[])', 'ktm_feature_state_procedure_owner'),
      ('feature.derive_subtype_public_ready()', 'ktm_feature_state_procedure_owner'),
      ('feature.sync_subtype_public_ready()', 'ktm_feature_state_procedure_owner'),
      ('feature.reject_user_feature_version_mutation()', 'ktm_feature_state_procedure_owner'),
      ('feature.reject_feature_change_request_receipt_mutation()', 'ktm_feature_state_procedure_owner'),
      ('feature.write_feature_state_transition()', 'ktm_feature_audit_writer'),
      ('feature.reject_feature_state_transition_mutation()', 'ktm_feature_audit_writer'),
      ('feature.reject_tvn40_append_only_mutation()', 'ktm_curation_audit_writer'),
      ('feature.reject_tvn40_truncate()', 'ktm_curation_audit_writer'),
      ('feature.validate_theme_candidate_merge_target()', 'ktm_curation_audit_writer'),
      ('feature.append_theme_feature_candidate_transition(uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,uuid,text,bigint,bigint,text,text,uuid,bigint,text,text,uuid,uuid,bigint,text,text,jsonb)', 'ktm_curation_audit_writer'),
      ('feature.reject_curation_provider_receipt_mutation()', 'ktm_curation_audit_writer'),
      ('feature.current_curation_rule_input(uuid)', 'ktm_curation_command_owner'),
      ('feature.reject_theme_feature_candidate(uuid,bigint,bigint,text,text)', 'ktm_curation_command_owner'),
      ('feature.current_theme_candidate_snapshot(uuid,text,text)', 'ktm_curation_command_owner'),
      ('feature.promote_theme_feature_candidate(uuid,uuid,text,text,text,text,text,text,integer,text,text,text,bigint,bigint,bigint,bigint,text,text)', 'ktm_curation_command_owner'),
      ('feature.materialize_theme_candidate_generation(uuid,text,uuid,uuid,bigint,text,jsonb)', 'ktm_curation_command_owner'),
      ('feature.claim_curation_catalog_command_effect(bigint,text,text,uuid)', 'ktm_curation_command_owner'),
      ('feature.create_curation_rule_reconcile_receipt(uuid,text,bigint,bigint,text,text,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.create_curated_source_rule_command(uuid,uuid,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.patch_curated_source_rule_command(uuid,bigint,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.archive_curated_source_rule_command(uuid,bigint,bigint,text,text)', 'ktm_curation_command_owner'),
      ('feature.create_curated_theme_command(text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.patch_curated_theme_command(uuid,bigint,text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.archive_curated_theme_command(uuid,bigint,bigint,text,text)', 'ktm_curation_command_owner'),
      ('feature.create_curated_source_command(bigint,text,text,text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.patch_curated_source_command(uuid,bigint,text,text,text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.archive_curated_source_command(uuid,bigint,bigint,text,text)', 'ktm_curation_command_owner'),
      ('feature.create_curation_collection_command(text,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.patch_curation_collection_command(uuid,bigint,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.archive_curation_collection_command(uuid,bigint,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.create_curation_item_command(uuid,text,text,text,text,text,text,text,integer,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.patch_curation_item_command(uuid,uuid,bigint,text,text,text,text,text,text,text,integer,text,text,text,text,jsonb,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.archive_curation_item_command(uuid,uuid,bigint,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.resolve_curation_import_collection_command(text,uuid,uuid,text,text,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.touch_curation_import_collection_command(uuid,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.reclassify_curation_quarantine_command(uuid,bigint,text,uuid,bigint,uuid[],text,text,bigint,text)', 'ktm_curation_command_owner'),
      ('ops.reject_curation_import_collection_effect_mutation()', 'ktm_curation_audit_writer'),
      ('ops.reject_curation_import_collection_effect_truncate()', 'ktm_curation_audit_writer'),
      ('feature.refresh_curated_source_observation(bigint,uuid)', 'ktm_curation_command_owner'),
      ('feature.finalize_provider_curation_receipts(bigint,uuid,text,text)', 'ktm_curation_command_owner'),
      ('feature.seal_provider_curation_snapshot_receipt(uuid,bigint,text,text,bigint,text)', 'ktm_curation_command_owner'),
      ('feature.finalize_provider_curation_root(uuid)', 'ktm_curation_command_owner'),
      ('feature.sync_concierge_theme_catalog(bigint,uuid)', 'ktm_curation_command_owner'),
      ('feature.sync_concierge_catalog_after_observation()', 'ktm_curation_command_owner'),
      ('ops.ensure_provider_feature_operation_command(text,text,text,jsonb,timestamptz,timestamptz,text)', 'ktm_curation_command_owner'),
      ('ops.finish_provider_feature_membership_command(uuid,bigint,text,text,boolean,timestamptz)', 'ktm_curation_command_owner'),
      ('ops.append_provider_feature_attempt_event_command(text,bigint,text,text,integer,text,jsonb)', 'ktm_curation_command_owner'),
      ('ops.transition_provider_feature_operation_terminal_command(uuid,text,text,text,text,timestamptz,timestamptz,boolean)', 'ktm_curation_command_owner'),
      ('ops.fill_provider_cancellation_starts_command(uuid,text,timestamptz)', 'ktm_curation_command_owner'),
      ('ops.transition_provider_cancellation_job_command(uuid,uuid,text,text[],text,text,text,timestamptz,timestamptz,boolean,text,text[])', 'ktm_curation_command_owner')
), existing AS (
    SELECT signature, owner_role, pg_proc.prokind
    FROM dedicated_routine
    JOIN pg_catalog.pg_proc ON pg_proc.oid = to_regprocedure(signature)
)
SELECT format(
    'ALTER %s %s OWNER TO %I',
    CASE prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END,
    signature,
    owner_role
)
FROM existing
\gexec

SELECT format('ALTER TYPE %I.%I OWNER TO ktm_feature_schema_owner', nspname, typname)
FROM pg_catalog.pg_type
JOIN pg_catalog.pg_namespace ON pg_namespace.oid = pg_type.typnamespace
WHERE nspname IN ('feature', 'provider_sync', 'ops')
  AND typtype IN ('b', 'c', 'd', 'e', 'r')
  AND typelem = 0
  AND typrelid = 0
\gexec

-- Ownership transfer removes old table ACLs. Do not restore them with
-- ``ON ALL TABLES`` or default privileges: feature contains the procedure-only
-- state/audit fence, and a later relation must never silently become mutable by
-- API/Dagster. The migrator runs an explicit inventory reconciler post-Alembic.
GRANT USAGE ON SCHEMA feature, provider_sync, ops TO ktm_feature_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA feature, provider_sync, ops
    FROM ktm_feature_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA feature, provider_sync, ops
    FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA feature
    REVOKE ALL ON TABLES FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA provider_sync
    REVOKE ALL ON TABLES FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA ops
    REVOKE ALL ON TABLES FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA feature
    REVOKE ALL ON SEQUENCES FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA provider_sync
    REVOKE ALL ON SEQUENCES FROM ktm_feature_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner IN SCHEMA ops
    REVOKE ALL ON SEQUENCES FROM ktm_feature_runtime;
SQL

echo "kor-travel-map dedicated DB role bootstrap completed for $KOR_TRAVEL_MAP_POSTGRES_DB"
