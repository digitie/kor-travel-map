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
_CANONICAL_CONTRACT_GUC_STATEMENTS: Final[tuple[str, ...]] = (
    "SET LOCAL quote_all_identifiers TO off",
    "SET LOCAL DateStyle TO 'ISO, YMD'",
    "SET LOCAL IntervalStyle TO 'postgres'",
    "SET LOCAL TimeZone TO 'UTC'",
    "SET LOCAL extra_float_digits TO 3",
    "SET LOCAL lc_numeric TO 'C'",
    "SET LOCAL bytea_output TO 'hex'",
    "SET LOCAL standard_conforming_strings TO on",
    "SET LOCAL xmlbinary TO 'base64'",
)
_REFERENCE_ARTIFACTS: Final[dict[str, str]] = {
    "schema.sql": "schema_sql_sha256",
    "seed.sql": "seed_sql_sha256",
    "application-catalog.sql": "catalog_contract_sql_sha256",
    "application-source-catalog.sha256": "source_catalog_contract_receipt_sha256",
    "application-destination-catalog.sha256": (
        "destination_catalog_contract_receipt_sha256"
    ),
    "application-seed.sql": "seed_contract_sql_sha256",
    "application-seed.sha256": "seed_contract_receipt_sha256",
    "application-privileged-residue.sql": "privileged_residue_contract_sql_sha256",
    "application-privileged-residue.sha256": "privileged_residue_contract_receipt_sha256",
    "application-source-alembic-version.sql": "source_alembic_version_contract_sql_sha256",
    "application-source-alembic-version.sha256": "source_alembic_version_contract_receipt_sha256",
    "application-destination-alembic-version.sql": "destination_alembic_version_contract_sql_sha256",
    "application-destination-alembic-version.sha256": "destination_alembic_version_contract_receipt_sha256",
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
        ("application-source-catalog.sha256", "source_catalog_contract_sha256"),
        (
            "application-destination-catalog.sha256",
            "destination_catalog_contract_sha256",
        ),
        ("application-seed.sha256", "seed_contract_sha256"),
        ("application-privileged-residue.sha256", "privileged_residue_contract_sha256"),
        ("application-source-alembic-version.sha256", "source_alembic_version_contract_sha256"),
        (
            "application-destination-alembic-version.sha256",
            "destination_alembic_version_contract_sha256",
        ),
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


def _set_canonical_contract_gucs() -> None:
    """fresh migration의 catalog receipt도 handoff/source oracle과 같은 출력 규칙을 쓴다."""

    raw_connection = op.get_bind().connection.driver_connection
    for statement in _CANONICAL_CONTRACT_GUC_STATEMENTS:
        await_only(raw_connection.execute(statement))


def _verify_contract_receipt(
    name: str,
    expected_sha256: str,
    expected_receipt_sha256: str,
) -> None:
    """fresh migration이 실제 DB의 immutable receipt까지 같은 transaction에서 닫는다.

    sidecar byte hash만 확인하면 candidate build 때의 oracle은 통과해도, 다른 extension
    inventory/ACL을 가진 fresh deployment가 raw `300`을 commit할 수 있다. canonical query의
    ordered ``item`` stream을 handoff와 같은 UTF-8/LF SHA-256으로 다시 계산해, mismatch면
    Alembic outer transaction 전체를 rollback한다.
    """

    sql = _read_sidecar(name, expected_sha256)
    raw_connection = op.get_bind().connection.driver_connection
    try:
        rows = await_only(raw_connection.fetch(sql))
    except Exception as exc:  # pragma: no cover - backend exception type is driver-owned
        raise RuntimeError(f"300 baseline {name} receipt query failed") from exc
    digest = hashlib.sha256()
    for row in rows:
        item = str(row["item"]).encode("utf-8")
        digest.update(item)
        digest.update(b"\n")
    observed_receipt_sha256 = digest.hexdigest()
    if observed_receipt_sha256 != expected_receipt_sha256:
        raise RuntimeError(
            f"300 baseline {name} receipt does not match immutable reference "
            f"(expected={expected_receipt_sha256}, observed={observed_receipt_sha256})"
        )


_FINAL_APPLICATION_ROLE_ASSERTIONS_SQL: Final[str] = r"""
DO $final_application_role_contract$
DECLARE
    observed_extension_inventory text[];
BEGIN
    -- known NOLOGIN/LOGIN checks below와 count를 결합해 reserved `ktm_*`
    -- namespace 전체가 exact 21개임을 보장한다. 이 guard가 없으면 unseen prefix
    -- principal이 ownership/ACL catalog boundary 밖에 남을 수 있다.
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname LIKE 'ktm\_%' ESCAPE '\'
    ) <> 21 THEN
        RAISE EXCEPTION '300 baseline requires the exact reserved application role inventory'
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
            WHERE granted.rolname LIKE 'ktm\_%' ESCAPE '\'
               OR member.rolname LIKE 'ktm\_%' ESCAPE '\'
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
        RAISE EXCEPTION '300 baseline requires the final database owner/search_path/role-settings contract'
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
        RAISE EXCEPTION '300 baseline requires the exact extension inventory contract'
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
        RAISE EXCEPTION '300 baseline extension bootstrap ownership/inventory contract is not exact'
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
        RAISE EXCEPTION '300 baseline extension member ownership contract is not exact'
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
        RAISE EXCEPTION '300 baseline does not accept unsupported extension member classes'
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


# fresh bootstrap의 virgin input guard와 같은 catalog boundary를 migration transaction
# 끝에서 다시 확인한다. bootstrap 뒤 public에는 exact fuzzystrmatch extension member와
# Alembic 자신의 version table만 남을 수 있다. 이 assertion은 generic fresh
# `upgrade head`가 source/handoff receipt와 다른 public ACL·extension/default-ACL 상태를
# 승인하지 않게 한다.
_FINAL_APPLICATION_CATALOG_ASSERTIONS_SQL: Final[str] = r"""
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
        RAISE EXCEPTION '300 baseline public schema ACL contract is not exact'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl) THEN
        RAISE EXCEPTION '300 baseline default privilege catalog must be empty'
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
        RAISE EXCEPTION '300 baseline procedural language inventory must be exact'
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
        RAISE EXCEPTION '300 baseline public.alembic_version contract is not exact'
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
        RAISE EXCEPTION '300 baseline replication topology must be empty'
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
        RAISE EXCEPTION '300 baseline public residue catalog is not empty'
            USING ERRCODE = '42501';
    END IF;
END
$final_application_catalog_contract$;
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
    op.execute("GRANT SELECT ON TABLE public.alembic_version TO ktm_feature_runtime")
    op.execute(_FINAL_APPLICATION_CATALOG_ASSERTIONS_SQL)
    _set_canonical_contract_gucs()
    _verify_contract_receipt(
        "application-catalog.sql",
        artifacts["catalog_contract_sql_sha256"],
        artifacts["source_catalog_contract_sha256"],
    )
    _verify_contract_receipt(
        "application-seed.sql",
        artifacts["seed_contract_sql_sha256"],
        artifacts["seed_contract_sha256"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "300_schema_baseline is forward-only — older Alembic lineages are unsupported"
    )
