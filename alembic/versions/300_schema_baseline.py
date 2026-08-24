"""`0236`의 final application schema를 재현하는 단일 root baseline.

Revision ID: 300
Revises: 없음 — active graph의 유일한 root

`0200_schema_baseline`부터 `0236_tvn41s_compaction_drained`까지의 source는 실행
graph가 아닌 retired archive로 보존한다. 새 DB는 final role bootstrap 뒤 이 migration
하나만 적용한다. 기존 DB의 `0236 → 300` metadata handoff는 일반 upgrade/stamp가 아닌
명시적인 one-shot protocol만 허용하며, 그 protocol의 guard는 ``alembic/env.py``가
소유한다.

sidecar는 provider 적재·fixture·acceptance data가 없는 isolated fresh `0236` reference
DB에서 ``scripts/build-baseline.sh``로 생성했다. 사람이 수정하는 파일이 아니며, 두
sidecar hash와 final role/ACL bootstrap assertion이 함께 이 baseline의 정본이다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "300"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_SHA256: Final[str] = (
    "01b5c8709145a31176ec3753fd32b4c91febc1011c0d7cbb4a931b4737f53d2c"
)
_SEED_SHA256: Final[str] = (
    "1872473b75e79d940a8cae0821418e3e14f8f445a48aa144d6bb6cf8bfabd80f"
)
_BASELINE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "baseline"


def _read_sidecar(name: str, expected_sha256: str) -> str:
    path = _BASELINE_DIR / name
    raw = path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise RuntimeError(
            f"alembic/baseline/{name} bytes drift — clean 0236 reference에서 다시 "
            f"생성·catalog 동등성 증명 뒤 hash를 갱신하라 (observed {observed})"
        )
    return raw.decode("utf-8")


def _execute_sql_script(sql: str) -> None:
    """asyncpg extended protocol에서도 sidecar의 다중 statement를 같은 transaction에 실행."""

    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


_FINAL_APPLICATION_ROLE_ASSERTIONS_SQL: Final[str] = r"""
DO $final_application_role_contract$
BEGIN
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
            OR rolbypassrls OR rolreplication
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
        RAISE EXCEPTION '300 baseline requires all final NOLOGIN application roles'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_migrator', 'ktm_feature_api_runtime',
            'ktm_feature_dagster_runtime'
        ) AND (
            NOT rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb
            OR rolcreaterole OR rolbypassrls OR rolreplication
        )
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname IN (
            'ktm_feature_migrator', 'ktm_feature_api_runtime',
            'ktm_feature_dagster_runtime'
        )
    ) <> 3 THEN
        RAISE EXCEPTION '300 baseline requires all final LOGIN application roles'
            USING ERRCODE = '42501';
    END IF;

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
            WHERE granted.rolname LIKE 'ktm_feature_%'
               OR granted.rolname LIKE 'ktm_curation_%'
               OR granted.rolname LIKE 'ktm_manual_%'
               OR member.rolname LIKE 'ktm_feature_%'
               OR member.rolname LIKE 'ktm_curation_%'
               OR member.rolname LIKE 'ktm_manual_%'
        )
        (SELECT * FROM expected EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION '300 baseline application role membership graph is not exact'
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
    ) <> 4 THEN
        RAISE EXCEPTION '300 baseline requires the final database/schema owner contract'
            USING ERRCODE = '42501';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_catalog.pg_extension AS installed
        JOIN pg_catalog.pg_namespace AS home ON home.oid = installed.extnamespace
        WHERE (installed.extname, home.nspname) IN (
            ('postgis', 'x_extension'),
            ('pgcrypto', 'x_extension'),
            ('pg_trgm', 'x_extension')
        )
    ) <> 3 THEN
        RAISE EXCEPTION '300 baseline requires postgis, pgcrypto, pg_trgm in x_extension'
            USING ERRCODE = '42P01';
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
                ('ktm_feature_migrator', false),
                ('ktm_feature_api_runtime', true),
                ('ktm_feature_dagster_runtime', true),
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
        RAISE EXCEPTION '300 baseline x_extension USAGE contract is not exact'
            USING ERRCODE = '42501';
    END IF;
END
$final_application_role_contract$;
"""


# baseline sidecar는 routine/table ACL을 해당 object owner role로 실행해야 한다. 일부
# owner는 final state에서 CREATE를 갖지 않지만 object owner 변경 직전에는 PostgreSQL이
# schema CREATE를 요구한다. fresh-300 bootstrap이 주는 그 좁은 임시 elevation은 sidecar
# 뒤 이 block에서 정확한 final schema ACL로 소거한다. old staged bootstrap을 재실행하거나
# migration 밖에서 broad CREATE를 남기는 경로는 허용하지 않는다.
_FINAL_SCHEMA_PRIVILEGE_NORMALIZATION_SQL: Final[str] = r"""
REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM PUBLIC;
REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM
    ktm_feature_state_procedure_owner,
    ktm_feature_audit_writer,
    ktm_feature_runtime,
    ktm_curation_command_owner,
    ktm_curation_audit_writer,
    ktm_curation_admin_executor,
    ktm_curation_provider_executor,
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


def upgrade() -> None:
    """final bootstrap이 완성된 fresh DB에 immutable sidecar를 적용한다."""

    op.execute(_FINAL_APPLICATION_ROLE_ASSERTIONS_SQL)
    _execute_sql_script(_read_sidecar("schema.sql", _SCHEMA_SHA256))
    _execute_sql_script(_FINAL_SCHEMA_PRIVILEGE_NORMALIZATION_SQL)
    _execute_sql_script(_read_sidecar("seed.sql", _SEED_SHA256))


def downgrade() -> None:
    raise RuntimeError(
        "300_schema_baseline is forward-only — older Alembic lineages are unsupported"
    )
