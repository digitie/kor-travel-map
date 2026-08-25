"""single-root `300`을 적용하는 disposable PostGIS test bootstrap.

운영 `baseline-300` phase와 같은 final role graph를 fresh test DB에 만든다. 과거
`0200`~`0236` 단계 replay를 흉내 내지 않는다. 이 helper는 final role/extension/temporary
schema-CREATE 전제를 만든 뒤 restricted migrator → schema owner로 `300`을 적용한다.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

from alembic.config import Config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

# 기존 integration runtime fixture가 사용하는 test-only credential를 유지한다.
# 값 자체는 testcontainer 내부에서만 쓰이며, `300` bootstrap으로 교체할 때 로그인
# 경계를 바꾸지 않기 위해 이름이 아니라 역할별 credential 계약을 보존한다.
_TEST_MIGRATOR_PASSWORD = "tvn34-test-only-migrator-password"
_TEST_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"

_NOLOGIN_ROLES = (
    "ktm_feature_schema_owner",
    "ktm_feature_state_procedure_owner",
    "ktm_feature_audit_writer",
    "ktm_feature_runtime",
    "ktm_curation_command_owner",
    "ktm_curation_audit_writer",
    "ktm_curation_admin_executor",
    "ktm_curation_provider_executor",
    "ktm_manual_feature_procedure_owner",
    "ktm_manual_feature_admin_executor",
    "ktm_feature_create_provider_executor",
    "ktm_feature_request_procedure_owner",
    "ktm_feature_request_service_executor",
    "ktm_feature_request_admin_executor",
    "ktm_manual_provider_dedup_procedure_owner",
    "ktm_manual_provider_dedup_detector_executor",
    "ktm_manual_provider_dedup_admin_executor",
    "ktm_feature_reference_reconciliation_service_executor",
)

_ROLE_GRANTS = (
    "GRANT ktm_feature_schema_owner TO ktm_feature_migrator "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_feature_runtime TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_runtime TO ktm_feature_dagster_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_state_procedure_owner TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_feature_audit_writer TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_curation_command_owner TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_curation_audit_writer TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_curation_admin_executor TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_curation_provider_executor TO ktm_feature_dagster_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_manual_feature_procedure_owner TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_manual_feature_admin_executor TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_create_provider_executor TO ktm_feature_dagster_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_request_procedure_owner TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_feature_request_service_executor TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_request_admin_executor TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_manual_provider_dedup_procedure_owner TO ktm_feature_schema_owner "
    "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
    "GRANT ktm_manual_provider_dedup_detector_executor TO ktm_feature_dagster_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_manual_provider_dedup_admin_executor TO ktm_feature_api_runtime "
    "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
    "GRANT ktm_feature_reference_reconciliation_service_executor "
    "TO ktm_feature_api_runtime WITH ADMIN FALSE, INHERIT TRUE, SET FALSE",
)


async def bootstrap_application_300_roles(engine: AsyncEngine) -> str:
    """fresh DB에 `300` migration precondition을 실제 runtime과 같이 만든다."""

    from sqlalchemy import text

    async with engine.begin() as connection:
        version_table = await connection.scalar(
            text("SELECT to_regclass('public.alembic_version')")
        )
        if version_table is not None:
            raise RuntimeError("application-300 test bootstrap requires a fresh DB")
        object_count = await connection.scalar(
            text(
                "SELECT count(*) FROM ("
                "SELECT 1 FROM pg_catalog.pg_class AS object "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = object.relnamespace "
                "WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops') "
                "AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
                "UNION ALL "
                "SELECT 1 FROM pg_catalog.pg_proc AS object "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = object.pronamespace "
                "WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops') "
                "UNION ALL "
                "SELECT 1 FROM pg_catalog.pg_type AS object "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = object.typnamespace "
                "WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops') "
                "AND object.typtype IN ('b', 'c', 'd', 'e', 'r')"
                ") AS application_object"
            )
        )
        if object_count != 0:
            raise RuntimeError("application-300 test bootstrap requires no application object")

        await connection.execute(
            text(
                """
                DO $application_300_roles$
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
                            || 'NOCREATEROLE NOBYPASSRLS NOREPLICATION '
                            || 'CONNECTION LIMIT -1 VALID UNTIL ''infinity''',
                            role_name
                        );
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
                    END LOOP;
                END
                $application_300_roles$;
                """
            )
        )
        for role, password in (
            ("ktm_feature_migrator", _TEST_MIGRATOR_PASSWORD),
            ("ktm_feature_api_runtime", _TEST_RUNTIME_PASSWORD),
            ("ktm_feature_dagster_runtime", _TEST_RUNTIME_PASSWORD),
        ):
            quoted_password = await connection.scalar(
                text("SELECT quote_literal(CAST(:password AS text))"),
                {"password": password},
            )
            assert isinstance(quoted_password, str)
            await connection.execute(
                text(
                    f"ALTER ROLE {role} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOBYPASSRLS NOREPLICATION CONNECTION LIMIT -1 "
                    "VALID UNTIL 'infinity' "
                    f"PASSWORD {quoted_password}"
                )
            )
        for statement in _ROLE_GRANTS:
            await connection.execute(text(statement))

        for schema in ("feature", "provider_sync", "ops", "x_extension"):
            await connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION ktm_feature_schema_owner")
            )
            await connection.execute(
                text(f"ALTER SCHEMA {schema} OWNER TO ktm_feature_schema_owner")
            )
        database_name = await connection.scalar(text("SELECT current_database()"))
        assert isinstance(database_name, str)
        quoted_database = '"' + database_name.replace('"', '""') + '"'
        await connection.execute(
            text(f"ALTER DATABASE {quoted_database} OWNER TO ktm_feature_schema_owner")
        )
        await connection.execute(
            text(
                f"ALTER DATABASE {quoted_database} SET search_path TO "
                "public, x_extension"
            )
        )

        postgis_schema = await connection.scalar(
            text(
                "SELECT namespace.nspname FROM pg_catalog.pg_extension AS extension "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = extension.extnamespace "
                "WHERE extension.extname = 'postgis'"
            )
        )
        if postgis_schema not in {None, "x_extension"}:
            raise RuntimeError(
                "application-300 test bootstrap requires postgis in x_extension; "
                "existing DB repair/drop is unsupported"
            )
        # `baseline-300` fresh bootstrap와 같은 full source extension inventory를 만든다.
        # 어떤 extension도 helper만 optional로 두지 않는다. 그러면 fresh test가 certified
        # production bootstrap과 다른 database를 조용히 승인할 수 있다.
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public")
        )
        for extension, schema in (
            ("postgis", "x_extension"),
            ("pg_trgm", "x_extension"),
            ("pgcrypto", "x_extension"),
            ("pg_prewarm", "x_extension"),
        ):
            await connection.execute(
                text(f"CREATE EXTENSION IF NOT EXISTS {extension} WITH SCHEMA {schema}")
            )
        expected_extensions = {
            ("fuzzystrmatch", "public"),
            ("pgcrypto", "x_extension"),
            ("pg_prewarm", "x_extension"),
            ("pg_trgm", "x_extension"),
            ("plpgsql", "pg_catalog"),
            ("postgis", "x_extension"),
        }
        observed_extensions = {
            (str(row.extname), str(row.nspname))
            for row in (
                await connection.execute(
                    text(
                        "SELECT extension.extname, namespace.nspname "
                        "FROM pg_catalog.pg_extension AS extension "
                        "JOIN pg_catalog.pg_namespace AS namespace "
                        "ON namespace.oid = extension.extnamespace"
                    )
                )
            ).mappings()
        }
        if observed_extensions != expected_extensions:
            raise RuntimeError(
                "application-300 test bootstrap extension inventory drifted: "
                f"{sorted(observed_extensions)!r}"
            )

        await connection.execute(text("REVOKE ALL ON SCHEMA x_extension FROM PUBLIC"))
        await connection.execute(
            text(
                "REVOKE ALL ON SCHEMA x_extension FROM "
                + ", ".join(_NOLOGIN_ROLES[1:])
                + ", ktm_feature_migrator, ktm_feature_api_runtime, "
                "ktm_feature_dagster_runtime"
            )
        )
        await connection.execute(
            text(
                "GRANT USAGE ON SCHEMA x_extension TO "
                "ktm_feature_schema_owner, ktm_feature_state_procedure_owner, "
                "ktm_feature_runtime, ktm_feature_api_runtime, "
                "ktm_feature_dagster_runtime, ktm_curation_command_owner, "
                "ktm_manual_provider_dedup_procedure_owner"
            )
        )
        await connection.execute(
            text("REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM PUBLIC")
        )
        await connection.execute(
            text(
                "GRANT USAGE, CREATE ON SCHEMA feature, provider_sync, ops TO "
                "ktm_feature_state_procedure_owner, ktm_feature_audit_writer, "
                "ktm_curation_command_owner, ktm_curation_audit_writer, "
                "ktm_manual_feature_procedure_owner, "
                "ktm_feature_request_procedure_owner, "
                "ktm_manual_provider_dedup_procedure_owner"
            )
        )
    return _TEST_MIGRATOR_PASSWORD


async def bootstrapped_application_300_migrator_dsn(async_dsn: str) -> str:
    """fresh DB를 final bootstrap하고 migrator LOGIN DSN을 반환한다."""

    from sqlalchemy.engine import make_url

    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(async_dsn, pool_size=1)
    try:
        password = await bootstrap_application_300_roles(engine)
    finally:
        await engine.dispose()
    return (
        make_url(async_dsn)
        .set(username="ktm_feature_migrator", password=password)
        .render_as_string(hide_password=False)
    )


async def upgrade_head_with_application_300_bootstrap(
    config: Config,
    admin_dsn: str,
) -> None:
    """fresh bootstrap 뒤 normal active `300` root를 production 경로로 적용한다."""

    import asyncio

    from alembic import command

    config.set_main_option(
        "sqlalchemy.url",
        await bootstrapped_application_300_migrator_dsn(admin_dsn),
    )
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, "head")


@contextlib.contextmanager
def alembic_schema_owner_role() -> Iterator[None]:
    """restricted migrator가 migration 동안만 schema owner로 전환하게 한다."""

    key = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"
    previous = os.environ.get(key)
    os.environ[key] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
