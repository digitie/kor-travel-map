"""``test_db`` — ``kortravelmap.infra.db`` async engine + DSN 정규화.

실 DB 없이 DSN 정규화 + engine 객체 타입만 확인 (실 connection은
``tests/integration/`` 책임). 엔진 생성 테스트는 ``asyncpg`` 미설치 환경에서
skip — pyproject.toml 본 의존이므로 CI/실 사용 환경에선 항상 통과.
"""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import kortravelmap.infra.db as db_module
from kortravelmap.infra.db import (
    _EXPECTED_RUNTIME_APPLICATION_PROCEDURES,
    _EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS,
    _RUNTIME_DB_PRIVILEGE_SQL,
    _runtime_db_privilege_problems,
    make_async_engine,
    make_async_session_factory,
    normalize_async_dsn,
)

_HAS_ASYNCPG = importlib.util.find_spec("asyncpg") is not None
_skip_no_asyncpg = pytest.mark.skipif(
    not _HAS_ASYNCPG,
    reason="asyncpg not installed (`pip install asyncpg`)",
)


# -- normalize_async_dsn ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # asyncpg는 그대로
        (
            "postgresql+asyncpg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # postgresql → asyncpg
        (
            "postgresql://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # postgres (alias) → asyncpg
        (
            "postgres://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # psycopg2 → asyncpg (testcontainers 기본)
        (
            "postgresql+psycopg2://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # psycopg3 → asyncpg
        (
            "postgresql+psycopg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
    ],
)
def test_normalize_async_dsn_converts_to_asyncpg(raw: str, expected: str) -> None:
    """모든 PostgreSQL DSN을 ``postgresql+asyncpg://``로 통일."""
    assert normalize_async_dsn(raw) == expected


def test_normalize_async_dsn_empty_raises() -> None:
    """빈 DSN은 ValueError."""
    with pytest.raises(ValueError, match="비어"):
        normalize_async_dsn("")


def test_normalize_async_dsn_non_postgres_raises() -> None:
    """PostgreSQL이 아닌 scheme은 ValueError."""
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_async_dsn("mysql://u:p@h/d")


# -- make_async_engine -----------------------------------------------------


@_skip_no_asyncpg
def test_make_async_engine_returns_async_engine() -> None:
    """``AsyncEngine`` 인스턴스를 반환한다 (실 connection 시도 없음)."""
    engine = make_async_engine("postgresql://u:p@localhost:5432/test")
    assert isinstance(engine, AsyncEngine)
    # asyncpg driver가 박혔는지 확인
    assert "asyncpg" in str(engine.url)


@_skip_no_asyncpg
def test_make_async_engine_accepts_secretstr() -> None:
    """``KorTravelMapSettings.pg_dsn`` (SecretStr)를 그대로 받는다."""
    secret = SecretStr("postgresql://u:p@localhost:5432/test")
    engine = make_async_engine(secret)
    assert isinstance(engine, AsyncEngine)
    assert "asyncpg" in str(engine.url)


@_skip_no_asyncpg
def test_make_async_engine_respects_echo_flag() -> None:
    """``echo`` 옵션이 engine에 전달된다."""
    engine_off = make_async_engine("postgresql://u:p@h/d", echo=False)
    engine_on = make_async_engine("postgresql://u:p@h/d", echo=True)
    assert engine_off.echo is False
    assert engine_on.echo is True


def test_make_async_engine_passes_copied_server_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """session setting을 asyncpg connect args로 복사해 전달한다."""
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_async_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)
    server_settings = {"jit": "off"}

    engine = make_async_engine(
        "postgresql://u:p@h/d",
        server_settings=server_settings,
    )
    server_settings["jit"] = "on"

    assert engine is sentinel
    assert captured["connect_args"] == {"server_settings": {"jit": "off"}}


# -- ADR-090 runtime privilege preflight -----------------------------------


def _runtime_privilege_row(
    login: str = "ktm_feature_api_runtime",
) -> dict[str, object]:
    """정상 runtime catalog receipt의 최소 모형."""

    return {
        "session_user": login,
        "current_user": login,
        "is_superuser": False,
        "can_create_role": False,
        "bypasses_rls": False,
        "has_schema_owner_membership": False,
        "can_set_schema_owner_role": False,
        "can_set_runtime_group_role": False,
        "can_create_in_feature_schema": False,
        "can_read_public_features": True,
        "can_read_feature_override_field_paths": True,
        "can_execute_create_procedure": login == "ktm_feature_dagster_runtime",
        "can_execute_manual_create_procedure": login == "ktm_feature_api_runtime",
        "can_execute_transition_procedure": True,
        "can_execute_author_lifecycle_override_procedure": True,
        "can_execute_revoke_lifecycle_override_procedure": True,
        "can_execute_provider_field_patch_procedure": True,
        "can_execute_field_override_author_procedure": True,
        "can_execute_field_override_revoke_procedure": True,
        "can_execute_admin_transition_procedure": True,
        "can_execute_admin_reactivation_procedure": True,
        "executable_application_procedures": sorted(
            _EXPECTED_RUNTIME_APPLICATION_PROCEDURES[login]
        ),
        "executable_application_security_definer_functions": sorted(
            _EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS[login]
        ),
        "can_insert_feature_directly": False,
        "can_update_lifecycle_directly": False,
        "can_update_publication_directly": False,
        "can_update_quality_directly": False,
        "can_mutate_transition_audit_directly": False,
        "can_access_manual_feature_claims_directly": False,
        "can_access_feature_creation_origins_directly": False,
        "can_access_feature_requests_directly": False,
        "can_mutate_feature_overrides_directly": False,
        "can_mutate_feature_base_values_directly": False,
        "can_mutate_feature_override_registry_directly": False,
        "can_execute_audit_writer_directly": False,
    }


@pytest.mark.unit
def test_runtime_privilege_preflight_requires_procedures_but_denies_direct_dml() -> None:
    row = _runtime_privilege_row()

    assert _runtime_db_privilege_problems(
        row,
        expected_login="ktm_feature_api_runtime",
    ) == []

    row["can_update_quality_directly"] = True
    row["can_mutate_transition_audit_directly"] = True
    row["can_access_manual_feature_claims_directly"] = True
    row["can_access_feature_creation_origins_directly"] = True
    row["can_access_feature_requests_directly"] = True
    row["can_mutate_feature_overrides_directly"] = True
    row["can_mutate_feature_base_values_directly"] = True
    row["can_mutate_feature_override_registry_directly"] = True
    row["can_execute_transition_procedure"] = False
    row["can_read_public_features"] = False
    row["can_read_feature_override_field_paths"] = False
    row["can_execute_author_lifecycle_override_procedure"] = False
    row["can_execute_provider_field_patch_procedure"] = False
    row["can_execute_field_override_author_procedure"] = False
    row["can_execute_field_override_revoke_procedure"] = False
    row["can_execute_admin_transition_procedure"] = False
    row["can_execute_admin_reactivation_procedure"] = False
    executable_application_procedures = row["executable_application_procedures"]
    assert isinstance(executable_application_procedures, list)
    row["executable_application_procedures"] = [
        *executable_application_procedures,
        "feature.unintended_runtime_procedure()",
    ]
    executable_functions = row[
        "executable_application_security_definer_functions"
    ]
    assert isinstance(executable_functions, list)
    row["executable_application_security_definer_functions"] = [
        *executable_functions,
        "ops.unintended_runtime_function()",
    ]
    problems = _runtime_db_privilege_problems(
        row,
        expected_login="ktm_feature_api_runtime",
    )

    assert "runtime login must not UPDATE feature.features.quality_state directly" in problems
    assert "runtime login must not mutate feature.feature_state_transitions directly" in problems
    assert "runtime login must not access manual Feature identity claims directly" in problems
    assert "runtime login must not access Feature creation origins directly" in problems
    assert "runtime login must not access Feature requests directly" in problems
    assert "runtime login must not mutate ops.feature_overrides directly" in problems
    assert (
        "runtime login must not mutate feature.feature_base_field_values directly"
        in problems
    )
    assert (
        "runtime login must not mutate ops.feature_override_field_paths directly"
        in problems
    )
    assert "runtime login must EXECUTE transition_feature_state" in problems
    assert "runtime login must SELECT feature.public_features" in problems
    assert "runtime login must SELECT ops.feature_override_field_paths" in problems
    assert "runtime login must EXECUTE author_lifecycle_override" in problems
    assert "runtime login must EXECUTE apply_provider_feature_field_patch" in problems
    assert "runtime login must EXECUTE author_feature_field_overrides" in problems
    assert "runtime login must EXECUTE revoke_feature_field_overrides" in problems
    assert "runtime login must EXECUTE transition_admin_feature_state" in problems
    assert "runtime login must EXECUTE reactivate_admin_feature_state" in problems
    assert "API runtime must EXECUTE create_admin_manual_feature_with_initial_state" not in problems
    assert any(
        problem.startswith(
            "runtime login must not EXECUTE unexpected application procedures: "
        )
        for problem in problems
    )
    assert any(
        "unexpected application SECURITY DEFINER functions" in problem
        for problem in problems
    )


@pytest.mark.unit
def test_runtime_privilege_preflight_uses_role_specific_exact_procedure_sets() -> None:
    api_row = _runtime_privilege_row()
    dagster_row = _runtime_privilege_row("ktm_feature_dagster_runtime")

    assert _runtime_db_privilege_problems(
        api_row,
        expected_login="ktm_feature_api_runtime",
    ) == []

    api_row["can_execute_create_procedure"] = True
    api_row["can_execute_manual_create_procedure"] = False
    api_boundary_problems = _runtime_db_privilege_problems(
        api_row,
        expected_login="ktm_feature_api_runtime",
    )
    assert (
        "API runtime must not EXECUTE create_feature_with_initial_state directly"
        in api_boundary_problems
    )
    assert (
        "API runtime must EXECUTE create_admin_manual_feature_with_initial_state"
        in api_boundary_problems
    )
    api_row = _runtime_privilege_row()
    assert _runtime_db_privilege_problems(
        dagster_row,
        expected_login="ktm_feature_dagster_runtime",
    ) == []

    dagster_procedures = list(dagster_row["executable_application_procedures"])
    dagster_procedures.append(
        "feature.reject_theme_feature_candidate(uuid,bigint,bigint,text,text)"
    )
    dagster_row["executable_application_procedures"] = dagster_procedures
    problems = _runtime_db_privilege_problems(
        dagster_row,
        expected_login="ktm_feature_dagster_runtime",
    )
    assert any("unexpected application procedures" in problem for problem in problems)

    api_procedures = list(api_row["executable_application_procedures"])
    api_procedures.remove(
        "feature.archive_curation_collection_command(uuid,bigint,bigint,text)"
    )
    api_row["executable_application_procedures"] = api_procedures
    problems = _runtime_db_privilege_problems(
        api_row,
        expected_login="ktm_feature_api_runtime",
    )
    assert any("missing expected application procedures" in problem for problem in problems)

    api_functions = list(
        api_row["executable_application_security_definer_functions"]
    )
    api_functions.remove(
        "ops.fill_provider_cancellation_starts_command("
        "uuid,text,timestamp with time zone)"
    )
    api_row["executable_application_security_definer_functions"] = api_functions
    problems = _runtime_db_privilege_problems(
        api_row,
        expected_login="ktm_feature_api_runtime",
    )
    assert any(
        "missing expected application SECURITY DEFINER functions" in problem
        for problem in problems
    )


@pytest.mark.unit
def test_runtime_privilege_query_uses_postgres_function_privilege_for_procedures() -> None:
    """PG 16은 procedure도 ``has_function_privilege(...::regprocedure)``로 조회한다."""

    rendered = str(_RUNTIME_DB_PRIVILEGE_SQL)
    assert "has_function_privilege" in rendered
    assert "has_procedure_privilege" not in rendered
    assert "author_lifecycle_override" in rendered
    assert "revoke_lifecycle_override" in rendered
    assert "apply_provider_feature_field_patch" in rendered
    assert "author_feature_field_overrides" in rendered
    assert "revoke_feature_field_overrides" in rendered
    assert "transition_admin_feature_state" in rendered
    assert "reactivate_admin_feature_state" in rendered
    assert "executable_application_procedures" in rendered
    assert "executable_application_security_definer_functions" in rendered
    assert "candidate_routine.oid::regprocedure::text" in rendered
    assert "candidate_schema.nspname IN ('feature', 'provider_sync', 'ops')" in rendered
    # audit INSERT/UPDATE/DELETE/TRUNCATE 중 어느 하나라도 새면 preflight가 막는다.
    assert "'feature.feature_state_transitions', 'INSERT'" in rendered
    assert "'feature.feature_state_transitions', 'UPDATE'" in rendered
    assert "'feature.feature_state_transitions', 'DELETE'" in rendered
    assert "'feature.feature_state_transitions', 'TRUNCATE'" in rendered
    assert "'ops.feature_overrides', 'UPDATE'" in rendered
    assert "'ops.feature_overrides', 'DELETE'" in rendered
    assert "'feature.feature_base_field_values', 'INSERT'" in rendered
    assert "'ops.feature_override_field_paths', 'UPDATE'" in rendered
    assert "can_read_public_features" in rendered
    assert "can_read_feature_override_field_paths" in rendered


# -- make_async_session_factory -------------------------------------------


@_skip_no_asyncpg
def test_session_factory_is_async_sessionmaker() -> None:
    """``async_sessionmaker`` 인스턴스를 반환한다."""
    engine = make_async_engine("postgresql://u:p@h/d")
    factory = make_async_session_factory(engine)
    assert isinstance(factory, async_sessionmaker)
