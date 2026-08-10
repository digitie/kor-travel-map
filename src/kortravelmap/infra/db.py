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
        has_table_privilege(session_user, 'feature.feature_versions', 'SELECT')
            AS can_read_feature_versions,
        -- PostgreSQL stores functions and procedures in pg_proc; the public
        -- privilege inquiry is has_function_privilege even for a regprocedure.
        has_function_privilege(
            session_user,
            'feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_create_procedure,
        has_function_privilege(
            session_user,
            'feature.transition_feature_state(text,text,text,text,bigint,jsonb)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_transition_procedure,
        has_function_privilege(
            session_user,
            'feature.materialize_user_feature_change_provenance(text,text,uuid,text,text,bigint)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_provenance_procedure,
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
            'feature.materialize_provider_feature_version(text)'::regprocedure,
            'EXECUTE'
        ) AS can_execute_provider_version_procedure,
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
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS candidate_procedure
            JOIN pg_catalog.pg_namespace AS candidate_schema
              ON candidate_schema.oid = candidate_procedure.pronamespace
            WHERE candidate_schema.nspname = 'feature'
              AND candidate_procedure.prokind = 'p'
              AND has_function_privilege(
                    session_user,
                    candidate_procedure.oid,
                    'EXECUTE'
              )
              AND candidate_procedure.oid NOT IN (
                    'feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)'::regprocedure,
                    'feature.transition_feature_state(text,text,text,text,bigint,jsonb)'::regprocedure,
                    'feature.materialize_user_feature_change_provenance(text,text,uuid,text,text,bigint)'::regprocedure,
                    'feature.author_lifecycle_override(text,text,text,boolean,text,text,bigint)'::regprocedure,
                    'feature.revoke_lifecycle_override(text,text,bigint)'::regprocedure,
                    'feature.materialize_provider_feature_version(text)'::regprocedure,
                    'feature.transition_admin_feature_state('
                    'text,text,text,text,bigint,text,text,text)'::regprocedure,
                    'feature.reactivate_admin_feature_state('
                    'text,bigint,text,text,bigint,text,text)'::regprocedure
              )
        ) AS can_execute_unintended_feature_procedure,
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
            has_table_privilege(session_user, 'ops.feature_overrides', 'INSERT')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'UPDATE')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'DELETE')
            OR has_table_privilege(session_user, 'ops.feature_overrides', 'TRUNCATE')
        ) AS can_mutate_feature_overrides_directly,
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
        "can_execute_unintended_feature_procedure": (
            "runtime login must not EXECUTE an unintended feature procedure"
        ),
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
        "can_mutate_feature_overrides_directly": (
            "runtime login must not mutate ops.feature_overrides directly"
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
        "can_read_feature_versions": (
            "runtime login must SELECT retained feature.feature_versions"
        ),
        "can_execute_create_procedure": (
            "runtime login must EXECUTE create_feature_with_initial_state"
        ),
        "can_execute_transition_procedure": (
            "runtime login must EXECUTE transition_feature_state"
        ),
        "can_execute_provenance_procedure": (
            "runtime login must EXECUTE materialize_user_feature_change_provenance"
        ),
        "can_execute_author_lifecycle_override_procedure": (
            "runtime login must EXECUTE author_lifecycle_override"
        ),
        "can_execute_revoke_lifecycle_override_procedure": (
            "runtime login must EXECUTE revoke_lifecycle_override"
        ),
        "can_execute_provider_version_procedure": (
            "runtime login must EXECUTE materialize_provider_feature_version"
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
