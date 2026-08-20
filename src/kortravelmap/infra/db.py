"""``kortravelmap.infra.db`` — SQLAlchemy 2 async engine + session factory.

라이브러리 자체는 engine instance를 만들지 않는다. 호출자(api / Dagster /
테스트)가 ``KorTravelMapSettings.pg_dsn``으로 engine을 만들고 client/repo에
주입한다 (ADR-003 함수 라이브러리 + ADR-004 raw SQL).

본 모듈은 두 헬퍼만 제공한다:

- ``make_async_engine(dsn)`` — DSN → ``AsyncEngine`` (asyncpg driver 강제).
- ``make_async_session_factory(engine)`` — ``AsyncEngine`` →
  ``async_sessionmaker[AsyncSession]``.

ADR 참조
--------
- ADR-002 — async-only API
- ADR-003 — 호출자는 engine을 주입
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-007 — PostgreSQL 16 + SQLAlchemy 2 async + asyncpg
- ADR-008 — extension은 ``x_extension`` schema 격리

Sprint 1 scope
--------------
본 PR(#21)은 engine/session factory + testcontainers conftest. ORM 모델
(``infra/models.py``)과 repository(``infra/feature_repo.py``)는 Sprint 2
첫 provider 적재 직전 PR.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

    from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "RuntimeDbPrivilegeBoundaryError",
    "assert_runtime_db_privilege_boundary",
    "make_async_engine",
    "make_async_session_factory",
    "normalize_async_dsn",
]


_ASYNCPG_PREFIX: str = "postgresql+asyncpg://"
"""SQLAlchemy 2 async DSN scheme — asyncpg driver 강제."""


class RuntimeDbPrivilegeBoundaryError(RuntimeError):
    """실제 runtime DB session이 ADR-090 권한 경계를 벗어났을 때의 기동 오류."""


_GENERIC_FEATURE_CREATE_PROCEDURE = (
    "feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)"
)

_SHARED_RUNTIME_FEATURE_PROCEDURES = frozenset(
    {
        "feature.apply_provider_feature_field_patch(text,bigint,text,text,bigint,jsonb,jsonb)",
        "feature.author_feature_field_overrides(text,bigint,text,text,bigint,jsonb,jsonb)",
        "feature.author_lifecycle_override(text,text,text,boolean,text,text,bigint)",
        "feature.reactivate_admin_feature_state(text,bigint,text,text,bigint,text,text)",
        "feature.revoke_feature_field_overrides(text,bigint,text,text,bigint,text[])",
        "feature.revoke_lifecycle_override(text,text,bigint)",
        "feature.transition_admin_feature_state(text,text,text,text,bigint,text,text,text)",
        "feature.transition_feature_state(text,text,text,text,bigint,jsonb)",
    }
)

_MANUAL_FEATURE_CREATE_PROCEDURE = (
    "feature.create_admin_manual_feature_with_initial_state(jsonb,bigint)"
)
_MANUAL_FEATURE_PROVENANCE_FUNCTION = "feature.read_admin_manual_feature_provenance(uuid)"
_MANUAL_CURATION_FEATURE_CREATE_PROCEDURE = (
    "feature.create_manual_curation_item_with_feature_command(jsonb,jsonb,bigint)"
)

_ADMIN_CURATION_FEATURE_PROCEDURES = frozenset(
    {
        _MANUAL_CURATION_FEATURE_CREATE_PROCEDURE,
        "feature.apply_curation_import_items_command(jsonb,text,text,bigint,text)",
        # 0222 — canonical collections lock. admin executor만(dedup review 라우터·ktmctl).
        "feature.merge_lock_curation_collections(text,text)",
        "feature.archive_curated_source_command(uuid,bigint,bigint,text,text)",
        "feature.archive_curated_source_rule_command(uuid,bigint,bigint,text,text)",
        "feature.archive_curated_theme_command(uuid,bigint,bigint,text,text)",
        "feature.archive_curation_collection_command(uuid,bigint,bigint,text)",
        "feature.archive_curation_item_command(uuid,uuid,bigint,bigint,text)",
        "feature.claim_curation_import_plan_command(uuid,text,bigint,text)",
        "feature.complete_curation_import_plan_command(uuid,bigint,uuid,jsonb,text)",
        (
            "feature.create_curated_source_command("
            "bigint,text,text,text,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.create_curated_source_rule_command("
            "uuid,uuid,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)"
        ),
        "feature.create_curated_theme_command(text,text,text,text,text,jsonb,bigint,text)",
        (
            "feature.create_curation_collection_command("
            "text,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.create_curation_import_plan_command("
            "uuid,text,text,text,jsonb,jsonb,jsonb,timestamp with time zone,bigint,text)"
        ),
        (
            "feature.create_curation_item_command("
            "uuid,text,text,text,text,text,text,text,integer,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.materialize_theme_candidate_generation("
            "uuid,text,uuid,uuid,bigint,text,jsonb)"
        ),
        (
            "feature.patch_curated_source_command("
            "uuid,bigint,text,text,text,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.patch_curated_source_rule_command("
            "uuid,bigint,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)"
        ),
        (
            "feature.patch_curated_theme_command("
            "uuid,bigint,text,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.patch_curation_collection_command("
            "uuid,bigint,uuid,uuid,text,text,text,text,text,jsonb,bigint,text)"
        ),
        (
            "feature.patch_curation_item_command("
            "uuid,uuid,bigint,text,text,text,text,text,text,text,integer,text,text,text,text,"
            "jsonb,bigint,text)"
        ),
        (
            "feature.promote_theme_feature_candidate("
            "uuid,uuid,text,text,text,text,text,text,integer,text,text,text,"
            "bigint,bigint,bigint,bigint,text,text)"
        ),
        (
            "feature.reclassify_curation_quarantine_command("
            "uuid,bigint,text,uuid,bigint,uuid[],text,text,bigint,text)"
        ),
        "feature.reject_theme_feature_candidate(uuid,bigint,bigint,text,text)",
        (
            "feature.resolve_curation_import_collection_command("
            "text,uuid,uuid,text,text,bigint,text)"
        ),
        "feature.touch_curation_import_collection_command(uuid,bigint,text)",
    }
)

_PROVIDER_CURATION_FEATURE_PROCEDURES = frozenset(
    {
        "feature.finalize_provider_curation_root(uuid)",
        (
            "feature.seal_provider_curation_snapshot_receipt("
            "uuid,bigint,text,text,bigint,text)"
        ),
    }
)

_PROVIDER_OPERATION_PROCEDURES = frozenset(
    {
        (
            "ops.append_provider_feature_attempt_event_command("
            "text,bigint,text,text,integer,text,jsonb)"
        ),
        (
            "ops.ensure_provider_feature_operation_command("
            "text,text,text,jsonb,timestamp with time zone,timestamp with time zone,text)"
        ),
        (
            "ops.finish_provider_feature_membership_command("
            "uuid,bigint,text,text,boolean,timestamp with time zone)"
        ),
        (
            "ops.transition_provider_feature_operation_terminal_command("
            "uuid,text,text,text,text,timestamp with time zone,timestamp with time zone,boolean)"
        ),
    }
)

_ADMIN_CANCELLATION_SECURITY_DEFINER_FUNCTIONS = frozenset(
    {
        (
            "ops.fill_provider_cancellation_starts_command("
            "uuid,text,timestamp with time zone)"
        ),
        (
            "ops.transition_provider_cancellation_job_command("
            "uuid,uuid,text,text[],text,text,text,timestamp with time zone,"
            "timestamp with time zone,boolean,text,text[])"
        ),
    }
)

_EXPECTED_RUNTIME_APPLICATION_PROCEDURES = {
    "ktm_feature_api_runtime": (
        _SHARED_RUNTIME_FEATURE_PROCEDURES
        | frozenset({_MANUAL_FEATURE_CREATE_PROCEDURE})
        | _ADMIN_CURATION_FEATURE_PROCEDURES
    ),
    "ktm_feature_dagster_runtime": (
        _SHARED_RUNTIME_FEATURE_PROCEDURES
        | frozenset({_GENERIC_FEATURE_CREATE_PROCEDURE})
        | _PROVIDER_CURATION_FEATURE_PROCEDURES
        | _PROVIDER_OPERATION_PROCEDURES
    ),
}

_EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS = {
    "ktm_feature_api_runtime": _ADMIN_CANCELLATION_SECURITY_DEFINER_FUNCTIONS
    | frozenset({_MANUAL_FEATURE_PROVENANCE_FUNCTION}),
    "ktm_feature_dagster_runtime": frozenset(),
}


_RUNTIME_DB_PRIVILEGE_SQL = text(
    """
    SELECT
        session_user::text AS session_user,
        current_user::text AS current_user,
        runtime_role.rolsuper AS is_superuser,
        runtime_role.rolcreaterole AS can_create_role,
        runtime_role.rolbypassrls AS bypasses_rls,
        pg_has_role(session_user, 'ktm_feature_schema_owner', 'member')
            AS has_schema_owner_membership,
        pg_has_role(session_user, 'ktm_feature_schema_owner', 'SET')
            AS can_set_schema_owner_role,
        pg_has_role(session_user, 'ktm_feature_runtime', 'SET')
            AS can_set_runtime_group_role,
        has_schema_privilege(session_user, 'feature', 'CREATE')
            AS can_create_in_feature_schema,
        has_table_privilege(session_user, 'feature.public_features', 'SELECT')
            AS can_read_public_features,
        has_table_privilege(session_user, 'ops.feature_override_field_paths', 'SELECT')
            AS can_read_feature_override_field_paths,
        -- PostgreSQL stores functions and procedures in pg_proc; the public
        -- privilege inquiry is has_function_privilege even for a regprocedure.
        has_function_privilege(
            session_user,
            'feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_create_procedure,
        has_function_privilege(
            session_user,
            'feature.create_admin_manual_feature_with_initial_state(jsonb,bigint)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_manual_create_procedure,
        has_function_privilege(
            session_user,
            'feature.transition_feature_state(text,text,text,text,bigint,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_transition_procedure,
        has_function_privilege(
            session_user,
            'feature.author_lifecycle_override(text,text,text,boolean,text,text,bigint)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_author_lifecycle_override_procedure,
        has_function_privilege(
            session_user,
            'feature.revoke_lifecycle_override(text,text,bigint)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_revoke_lifecycle_override_procedure,
        has_function_privilege(
            session_user,
            'feature.apply_provider_feature_field_patch('
            'text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_provider_field_patch_procedure,
        has_function_privilege(
            session_user,
            'feature.author_feature_field_overrides('
            'text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_field_override_author_procedure,
        has_function_privilege(
            session_user,
            'feature.revoke_feature_field_overrides('
            'text,bigint,text,text,bigint,text[])'::regprocedure,
            'EXECUTE'
        ) AS can_execute_field_override_revoke_procedure,
        has_function_privilege(
            session_user,
            'feature.transition_admin_feature_state('
            'text,text,text,text,bigint,text,text,text)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_admin_transition_procedure,
        has_function_privilege(
            session_user,
            'feature.reactivate_admin_feature_state('
            'text,bigint,text,text,bigint,text,text)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_admin_reactivation_procedure,
        ARRAY(
            SELECT candidate_routine.oid::regprocedure::text
            FROM pg_catalog.pg_proc AS candidate_routine
            JOIN pg_catalog.pg_namespace AS candidate_schema
              ON candidate_schema.oid = candidate_routine.pronamespace
            WHERE candidate_schema.nspname IN ('feature', 'provider_sync', 'ops')
              AND candidate_routine.prokind = 'p'
              AND has_function_privilege(
                    session_user,
                    candidate_routine.oid,
                    'EXECUTE'
              )
            ORDER BY candidate_routine.oid::regprocedure::text
        ) AS executable_application_procedures,
        ARRAY(
            SELECT candidate_routine.oid::regprocedure::text
            FROM pg_catalog.pg_proc AS candidate_routine
            JOIN pg_catalog.pg_namespace AS candidate_schema
              ON candidate_schema.oid = candidate_routine.pronamespace
            WHERE candidate_schema.nspname IN ('feature', 'provider_sync', 'ops')
              AND candidate_routine.prokind = 'f'
              AND candidate_routine.prosecdef
              AND has_function_privilege(
                    session_user,
                    candidate_routine.oid,
                    'EXECUTE'
              )
            ORDER BY candidate_routine.oid::regprocedure::text
        ) AS executable_application_security_definer_functions,
        has_table_privilege(session_user, 'feature.features', 'INSERT')
            AS can_insert_feature_directly,
        has_column_privilege(session_user, 'feature.features', 'lifecycle_state', 'UPDATE')
            AS can_update_lifecycle_directly,
        has_column_privilege(session_user, 'feature.features', 'publication_state', 'UPDATE')
            AS can_update_publication_directly,
        has_column_privilege(session_user, 'feature.features', 'quality_state', 'UPDATE')
            AS can_update_quality_directly,
        (
            has_table_privilege(session_user, 'feature.feature_state_transitions', 'INSERT')
            OR has_table_privilege(session_user, 'feature.feature_state_transitions', 'UPDATE')
            OR has_table_privilege(session_user, 'feature.feature_state_transitions', 'DELETE')
            OR has_table_privilege(session_user, 'feature.feature_state_transitions', 'TRUNCATE')
        ) AS can_mutate_transition_audit_directly,
        (
            has_table_privilege(
                session_user, 'feature.manual_feature_identity_claims', 'SELECT'
            )
            OR has_table_privilege(
                session_user, 'feature.manual_feature_identity_claims', 'INSERT'
            )
            OR has_table_privilege(
                session_user, 'feature.manual_feature_identity_claims', 'UPDATE'
            )
            OR has_table_privilege(
                session_user, 'feature.manual_feature_identity_claims', 'DELETE'
            )
            OR has_table_privilege(
                session_user, 'feature.manual_feature_identity_claims', 'TRUNCATE'
            )
        ) AS can_access_manual_feature_claims_directly,
        (
            has_table_privilege(
                session_user, 'feature.feature_creation_origins', 'SELECT'
            )
            OR has_table_privilege(
                session_user, 'feature.feature_creation_origins', 'INSERT'
            )
            OR has_table_privilege(
                session_user, 'feature.feature_creation_origins', 'UPDATE'
            )
            OR has_table_privilege(
                session_user, 'feature.feature_creation_origins', 'DELETE'
            )
            OR has_table_privilege(
                session_user, 'feature.feature_creation_origins', 'TRUNCATE'
            )
        ) AS can_access_feature_creation_origins_directly,
        (
            has_table_privilege(session_user, 'ops.feature_overrides', 'INSERT')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'UPDATE')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'DELETE')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'TRUNCATE')
        ) AS can_mutate_feature_overrides_directly,
        (
            has_table_privilege(session_user, 'feature.feature_base_field_values', 'INSERT')
            OR has_table_privilege(session_user, 'feature.feature_base_field_values', 'UPDATE')
            OR has_table_privilege(session_user, 'feature.feature_base_field_values', 'DELETE')
            OR has_table_privilege(session_user, 'feature.feature_base_field_values', 'TRUNCATE')
        ) AS can_mutate_feature_base_values_directly,
        (
            has_table_privilege(session_user, 'ops.feature_override_field_paths', 'INSERT')
            OR has_table_privilege(session_user, 'ops.feature_override_field_paths', 'UPDATE')
            OR has_table_privilege(session_user, 'ops.feature_override_field_paths', 'DELETE')
            OR has_table_privilege(session_user, 'ops.feature_override_field_paths', 'TRUNCATE')
        ) AS can_mutate_feature_override_registry_directly,
        has_function_privilege(
            session_user,
            'feature.write_feature_state_transition()'::regprocedure,
            'EXECUTE'
        ) AS can_execute_audit_writer_directly
    FROM pg_catalog.pg_roles AS runtime_role
    WHERE runtime_role.rolname = session_user
    """
)


def _runtime_db_privilege_problems(
    row: Mapping[str, object],
    *,
    expected_login: str,
) -> list[str]:
    """catalog receipt 한 행을 사람이 읽을 수 있는 fail-closed 원인으로 바꾼다."""

    problems: list[str] = []
    if row.get("session_user") != expected_login:
        problems.append(f"session_user must be {expected_login!r}")
    if row.get("current_user") != row.get("session_user"):
        problems.append("session_user and current_user must be identical")

    forbidden_true_fields = {
        "is_superuser": "runtime login must not be SUPERUSER",
        "can_create_role": "runtime login must not have CREATEROLE",
        "bypasses_rls": "runtime login must not have BYPASSRLS",
        "has_schema_owner_membership": (
            "runtime login must not be a ktm_feature_schema_owner member"
        ),
        "can_set_schema_owner_role": (
            "runtime login must not SET ROLE ktm_feature_schema_owner"
        ),
        "can_set_runtime_group_role": (
            "runtime login must not SET ROLE ktm_feature_runtime"
        ),
        "can_create_in_feature_schema": "runtime login must not CREATE in feature schema",
        "can_insert_feature_directly": "runtime login must not INSERT feature.features directly",
        "can_update_lifecycle_directly": (
            "runtime login must not UPDATE feature.features.lifecycle_state directly"
        ),
        "can_update_publication_directly": (
            "runtime login must not UPDATE feature.features.publication_state directly"
        ),
        "can_update_quality_directly": (
            "runtime login must not UPDATE feature.features.quality_state directly"
        ),
        "can_mutate_transition_audit_directly": (
            "runtime login must not mutate feature.feature_state_transitions directly"
        ),
        "can_access_manual_feature_claims_directly": (
            "runtime login must not access manual Feature identity claims directly"
        ),
        "can_access_feature_creation_origins_directly": (
            "runtime login must not access Feature creation origins directly"
        ),
        "can_mutate_feature_overrides_directly": (
            "runtime login must not mutate ops.feature_overrides directly"
        ),
        "can_mutate_feature_base_values_directly": (
            "runtime login must not mutate feature.feature_base_field_values directly"
        ),
        "can_mutate_feature_override_registry_directly": (
            "runtime login must not mutate ops.feature_override_field_paths directly"
        ),
        "can_execute_audit_writer_directly": (
            "runtime login must not EXECUTE the audit writer function directly"
        ),
    }
    for field_name, message in forbidden_true_fields.items():
        if row.get(field_name) is not False:
            problems.append(message)

    required_true_fields = {
        "can_read_public_features": (
            "runtime login must SELECT feature.public_features"
        ),
        "can_read_feature_override_field_paths": (
            "runtime login must SELECT ops.feature_override_field_paths"
        ),
        "can_execute_transition_procedure": (
            "runtime login must EXECUTE transition_feature_state"
        ),
        "can_execute_author_lifecycle_override_procedure": (
            "runtime login must EXECUTE author_lifecycle_override"
        ),
        "can_execute_revoke_lifecycle_override_procedure": (
            "runtime login must EXECUTE revoke_lifecycle_override"
        ),
        "can_execute_provider_field_patch_procedure": (
            "runtime login must EXECUTE apply_provider_feature_field_patch"
        ),
        "can_execute_field_override_author_procedure": (
            "runtime login must EXECUTE author_feature_field_overrides"
        ),
        "can_execute_field_override_revoke_procedure": (
            "runtime login must EXECUTE revoke_feature_field_overrides"
        ),
        "can_execute_admin_transition_procedure": (
            "runtime login must EXECUTE transition_admin_feature_state"
        ),
        "can_execute_admin_reactivation_procedure": (
            "runtime login must EXECUTE reactivate_admin_feature_state"
        ),
    }
    for field_name, message in required_true_fields.items():
        if row.get(field_name) is not True:
            problems.append(message)

    if expected_login == "ktm_feature_api_runtime":
        if row.get("can_execute_create_procedure") is not False:
            problems.append(
                "API runtime must not EXECUTE create_feature_with_initial_state directly"
            )
        if row.get("can_execute_manual_create_procedure") is not True:
            problems.append(
                "API runtime must EXECUTE create_admin_manual_feature_with_initial_state"
            )
    elif expected_login == "ktm_feature_dagster_runtime":
        if row.get("can_execute_create_procedure") is not True:
            problems.append(
                "Dagster runtime must EXECUTE create_feature_with_initial_state"
            )
        if row.get("can_execute_manual_create_procedure") is not False:
            problems.append(
                "Dagster runtime must not EXECUTE the manual Feature writer"
            )

    expected_procedures = _EXPECTED_RUNTIME_APPLICATION_PROCEDURES.get(expected_login)
    if expected_procedures is None:
        problems.append(
            f"runtime privilege preflight has no procedure allowlist for {expected_login!r}"
        )
        return problems

    actual_procedures_value = row.get("executable_application_procedures")
    if not isinstance(actual_procedures_value, (list, tuple)):
        problems.append("runtime application procedure catalog must be a PostgreSQL text array")
        return problems
    actual_procedures = frozenset(
        procedure
        for procedure in actual_procedures_value
        if isinstance(procedure, str)
    )
    if len(actual_procedures) != len(actual_procedures_value):
        problems.append("runtime application procedure catalog must contain only text signatures")
        return problems

    missing_procedures = sorted(expected_procedures - actual_procedures)
    if missing_procedures:
        problems.append(
            "runtime login is missing expected application procedures: "
            + ", ".join(missing_procedures)
        )
    unexpected_procedures = sorted(actual_procedures - expected_procedures)
    if unexpected_procedures:
        problems.append(
            "runtime login must not EXECUTE unexpected application procedures: "
            + ", ".join(unexpected_procedures)
        )

    expected_functions = _EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS.get(
        expected_login
    )
    if expected_functions is None:
        problems.append(
            "runtime privilege preflight has no SECURITY DEFINER function allowlist for "
            f"{expected_login!r}"
        )
        return problems

    actual_functions_value = row.get(
        "executable_application_security_definer_functions"
    )
    if not isinstance(actual_functions_value, (list, tuple)):
        problems.append(
            "runtime application SECURITY DEFINER function catalog must be a "
            "PostgreSQL text array"
        )
        return problems
    actual_functions = frozenset(
        function for function in actual_functions_value if isinstance(function, str)
    )
    if len(actual_functions) != len(actual_functions_value):
        problems.append(
            "runtime application SECURITY DEFINER function catalog must contain only "
            "text signatures"
        )
        return problems

    missing_functions = sorted(expected_functions - actual_functions)
    if missing_functions:
        problems.append(
            "runtime login is missing expected application SECURITY DEFINER functions: "
            + ", ".join(missing_functions)
        )
    unexpected_functions = sorted(actual_functions - expected_functions)
    if unexpected_functions:
        problems.append(
            "runtime login must not EXECUTE unexpected application SECURITY DEFINER "
            "functions: "
            + ", ".join(unexpected_functions)
        )
    return problems


async def assert_runtime_db_privilege_boundary(
    engine: AsyncEngine,
    *,
    expected_login: str,
) -> None:
    """runtime DSN으로 ADR-090 procedure-only DB 권한 경계를 실제로 검증한다.

    이 검사는 migration/bootstrap role이 아닌 API·Dagster runtime login에서만 호출한다.
    catalog object나 state procedure가 누락된 DB도 안전한 "실패"로 다뤄 기동을 막는다.
    """

    try:
        async with engine.connect() as connection:
            row = (await connection.execute(_RUNTIME_DB_PRIVILEGE_SQL)).mappings().one_or_none()
    except Exception as exc:  # noqa: BLE001 - catalog/preflight 실패는 원인과 함께 기동 차단
        raise RuntimeDbPrivilegeBoundaryError(
            "runtime DB privilege preflight could not read the ADR-090 catalog boundary"
        ) from exc

    if row is None:
        raise RuntimeDbPrivilegeBoundaryError(
            "runtime DB privilege preflight could not resolve session_user in pg_roles"
        )

    # ``mappings()`` has string aliases in the query above; SQLAlchemy exposes
    # them as the wider ``RowMapping`` protocol, so retain that catalog contract
    # explicitly at this boundary.
    problems = _runtime_db_privilege_problems(
        cast(Mapping[str, object], row),
        expected_login=expected_login,
    )
    if problems:
        raise RuntimeDbPrivilegeBoundaryError(
            "runtime DB privilege preflight failed: " + "; ".join(problems)
        )


def normalize_async_dsn(dsn: str) -> str:
    """raw ``postgresql://`` / ``postgres://`` / ``psycopg2``-style DSN을
    SQLAlchemy ``postgresql+asyncpg://`` 형태로 정규화한다.

    testcontainers의 ``get_connection_url()``은 보통 ``postgresql+psycopg2://``
    또는 ``postgresql://``를 반환하므로 본 함수로 변환한다 (ADR-007 asyncpg).

    Parameters
    ----------
    dsn
        DSN. 예: ``postgresql://user:pw@host:5432/db``,
        ``postgresql+psycopg2://...``, 이미 ``postgresql+asyncpg://...``.

    Returns
    -------
    str
        ``postgresql+asyncpg://...`` 형태.

    Raises
    ------
    ValueError
        DSN이 PostgreSQL scheme이 아닌 경우.
    """
    if not dsn:
        raise ValueError("dsn은 비어 있을 수 없음.")
    if dsn.startswith(_ASYNCPG_PREFIX):
        return dsn
    if dsn.startswith("postgresql+psycopg2://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql+psycopg2://") :]
    if dsn.startswith("postgresql+psycopg://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql+psycopg://") :]
    if dsn.startswith("postgresql://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql://") :]
    if dsn.startswith("postgres://"):
        return _ASYNCPG_PREFIX + dsn[len("postgres://") :]
    raise ValueError(
        f"dsn={dsn!r}은 PostgreSQL scheme이 아님 "
        f"(postgresql:// 또는 postgresql+asyncpg:// 필요)."
    )


def require_pg_dsn(settings: KorTravelMapSettings) -> SecretStr:
    """runtime DSN을 꺼내거나, 없으면 그 사실을 명시적으로 알린다.

    ADR-090 이후 ``pg_dsn`` 기본값이 없다. 호출부마다 ``None`` 분기를 따로 쓰면
    같은 상황에 서로 다른 오류가 나오므로(``AttributeError``까지 섞였다) 한 자리로
    모은다. 문구는 API의 engine 초기화(`api/db.py`)와 같게 유지한다.
    """

    if settings.pg_dsn is None:
        raise RuntimeError(
            "KOR_TRAVEL_MAP_PG_DSN runtime DSN is required; "
            "no application DSN fallback exists"
        )
    return settings.pg_dsn


def make_async_engine(
    dsn: str | SecretStr,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
    server_settings: Mapping[str, str] | None = None,
) -> AsyncEngine:
    """``AsyncEngine`` 인스턴스를 만든다 (asyncpg driver).

    Parameters
    ----------
    dsn
        DSN. ``str`` 또는 Pydantic ``SecretStr`` (``KorTravelMapSettings.pg_dsn``).
        자동으로 ``postgresql+asyncpg://``로 정규화.
    echo
        SQL echo (디버그용). 운영에선 ``False``.
    pool_size
        connection pool 기본 크기.
    max_overflow
        pool 초과 허용량.
    pool_pre_ping
        체크아웃 시 ``SELECT 1`` 확인 (idle 끊김 방지). 운영 권장 ``True``.
    server_settings
        asyncpg 신규 연결에 적용할 PostgreSQL session setting. 호출자가
        명시한 설정만 전달하며 기본값은 빈 맵이다.

    Returns
    -------
    AsyncEngine
        호출자가 ``await engine.dispose()`` 책임을 진다.
    """
    raw_dsn = dsn.get_secret_value() if hasattr(dsn, "get_secret_value") else str(dsn)
    normalized = normalize_async_dsn(raw_dsn)
    return create_async_engine(
        normalized,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
        connect_args=(
            {"server_settings": dict(server_settings)}
            if server_settings is not None
            else {}
        ),
    )


def make_async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """``AsyncEngine`` → ``async_sessionmaker``.

    호출 측은 ``async with session_factory() as session:`` 패턴으로 사용한다.
    ``expire_on_commit=False`` — commit 후에도 ORM 인스턴스가 stale 되지 않게
    (단, 본 라이브러리는 raw SQL 위주이므로 거의 영향 없음).

    Parameters
    ----------
    engine
        ``make_async_engine``의 결과.

    Returns
    -------
    async_sessionmaker[AsyncSession]
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
