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
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from sqlalchemy.util.concurrency import await_only

from alembic import op

# ruff: noqa: E501

revision: str = "300"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASELINE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "baseline"
_REFERENCE_MANIFEST: Final[str] = "application-reference.json"
_REFERENCE_MANIFEST_SHA256: Final[str] = "application-reference.sha256"
_REFERENCE_SCHEMA: Final[str] = "kor-travel-map.application-baseline-reference.v1"
_REFERENCE_SOURCE: Final[dict[str, str]] = {
    "git_commit": "01d65b2ad4ee265a3ef6b01448f6abf573a906a8",
    "raw_alembic_revision": "0236_tvn41s_compaction_drained",
    "container_image": "postgis/postgis:16-3.5-alpine",
    "container_image_id": "sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c",
    "postgres_server_version_num": "160014",
    "postgis_extension_version": "3.5.6",
}
_REFERENCE_FRESH_SEED_RELATIONS: Final[tuple[str, ...]] = (
    "feature.curated_source_rules",
    "feature.curated_sources",
    "feature.curated_themes",
    "ops.feature_override_field_paths",
    "provider_sync.provider_dataset_operation_scopes",
    "provider_sync.provider_dataset_operations",
    "provider_sync.provider_datasets",
)
_REFERENCE_STATIC_SEED_RELATIONS: Final[tuple[str, ...]] = (
    "ops.feature_override_field_paths",
)
_REFERENCE_ARTIFACTS: Final[dict[str, str]] = {
    "schema.sql": "schema_sql_sha256",
    "seed.sql": "seed_sql_sha256",
    "application-catalog.sql": "catalog_contract_sql_sha256",
    "application-catalog.sha256": "catalog_contract_receipt_sha256",
    "application-seed.sql": "seed_contract_sql_sha256",
    "application-seed.sha256": "seed_contract_receipt_sha256",
    "application-runtime-invariants.sql": "runtime_invariants_sql_sha256",
}


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


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _reference_manifest_sha256() -> str:
    """materialize 단계가 함께 낸 manifest digest sidecar를 엄격히 읽는다.

    `300` artifact는 source-only materialize 단계에서 한 directory로 생성되고, 그
    결과는 final candidate image와 fresh-oracle receipt가 image digest/commit과 함께
    고정한다. Python literal을 따로 고쳐야만 새 artifact를 후보로 만들 수 있게 하면
    그 자체가 생성 증적의 순환 의존성이 된다. digest sidecar는 manifest와 함께 기계
    생성되며, 빈 값·공백·여러 줄을 허용하지 않는다.
    """

    path = _BASELINE_DIR / _REFERENCE_MANIFEST_SHA256
    raw = path.read_bytes()
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("300 baseline reference manifest digest is malformed") from exc
    if not _is_sha256(value) or raw != f"{value}\n".encode("ascii"):
        raise RuntimeError("300 baseline reference manifest digest is malformed")
    return value


def _baseline_reference() -> dict[str, Any]:
    """생성 artifact가 한 immutable receipt인지 fresh migration 전에 검증한다."""

    manifest_path = _BASELINE_DIR / _REFERENCE_MANIFEST
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _reference_manifest_sha256():
        raise RuntimeError("300 baseline reference manifest bytes drifted")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("300 baseline reference manifest is malformed") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != _REFERENCE_SCHEMA:
        raise RuntimeError("300 baseline reference manifest schema is invalid")
    source = manifest.get("source")
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(source, dict)
        or not isinstance(artifacts, dict)
        or {key: source.get(key) for key in _REFERENCE_SOURCE} != _REFERENCE_SOURCE
        or tuple(manifest.get("fresh_seed_relations") or ())
        != _REFERENCE_FRESH_SEED_RELATIONS
        or tuple(manifest.get("static_seed_relations") or ())
        != _REFERENCE_STATIC_SEED_RELATIONS
    ):
        raise RuntimeError("300 baseline reference manifest contract is invalid")
    for name, key in _REFERENCE_ARTIFACTS.items():
        expected = artifacts.get(key)
        if not _is_sha256(expected):
            raise RuntimeError(f"300 baseline reference artifact digest is invalid: {key}")
        _read_sidecar(name, expected)
    for receipt_name, receipt_key in (
        ("application-catalog.sha256", "catalog_contract_sha256"),
        ("application-seed.sha256", "seed_contract_sha256"),
    ):
        receipt = _read_sidecar(
            receipt_name, artifacts[_REFERENCE_ARTIFACTS[receipt_name]]
        ).strip()
        expected_receipt = artifacts.get(receipt_key)
        if not _is_sha256(expected_receipt) or receipt != expected_receipt:
            raise RuntimeError("300 baseline reference receipt/manifest drifted")
    return manifest


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
            OR rolcreaterole OR rolbypassrls OR rolreplication OR rolconnlimit <> -1
            OR rolvaliduntil IS DISTINCT FROM 'infinity'::timestamptz
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
                    WHERE role.rolname LIKE 'ktm_feature_%'
                       OR role.rolname LIKE 'ktm_curation_%'
                       OR role.rolname LIKE 'ktm_manual_%'
                )
            )
        ) OR (
            setting_row.setdatabase = (
                SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
            )
            AND setting_row.setrole IN (
                SELECT role.oid
                FROM pg_catalog.pg_roles AS role
                WHERE role.rolname LIKE 'ktm_feature_%'
                   OR role.rolname LIKE 'ktm_curation_%'
                   OR role.rolname LIKE 'ktm_manual_%'
            )
        )
    ) THEN
        RAISE EXCEPTION '300 baseline requires the final database owner/search_path/role-settings contract'
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


# live revision projection은 immutable seed가 아니다. 정상 운영 DML이 revision과
# timestamp를 계속 바꾸므로 `0236 → 300` handoff에서 historical exact value를 강제하면
# 정상 DB를 거절한다. fresh `300`만 최소 runtime row를 0에서 초기화하고, handoff는
# `application-runtime-invariants.sql`로 존재·카디널리티·범위만 확인한다.
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
    """final bootstrap이 완성된 fresh DB에 immutable sidecar를 적용한다."""

    manifest = _baseline_reference()
    artifacts = manifest["artifacts"]
    op.execute(_FINAL_APPLICATION_ROLE_ASSERTIONS_SQL)
    _execute_sql_script(_read_sidecar("schema.sql", artifacts["schema_sql_sha256"]))
    _execute_sql_script(_FINAL_SCHEMA_PRIVILEGE_NORMALIZATION_SQL)
    _execute_sql_script(_read_sidecar("seed.sql", artifacts["seed_sql_sha256"]))
    _execute_sql_script(_RUNTIME_PROJECTION_INITIALIZATION_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "300_schema_baseline is forward-only — older Alembic lineages are unsupported"
    )
