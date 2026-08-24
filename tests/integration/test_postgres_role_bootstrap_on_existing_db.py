"""`baseline-300` role bootstrap은 기존 application DB를 절대 고치지 않는다.

`300`은 fresh DB만의 단일 root다. 이전 `0236` DB에서 role/소유권을 고치거나
extension을 옮기는 bootstrap은 전환 계약이 아니며, 별도 Docker Manager one-shot
handoff만 허용한다. 따라서 application object 또는 `alembic_version`이 있는 DB에서는
스크립트가 role, schema, extension, relation 어느 것도 변경하기 전에 실패해야 한다.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "docker" / "postgres-role-bootstrap.sh"
_DATABASE = "ktm_bootstrap_existing"


def _sync_dsn(raw_dsn: str, database: str) -> str:
    """psql이 그대로 먹을 수 있는 libpq URL."""

    from sqlalchemy.engine import make_url

    url = make_url(raw_dsn).set(drivername="postgresql", database=database)
    return url.render_as_string(hide_password=False)


async def _seed_existing_objects(dsn: str) -> None:
    """fresh-only guard가 인식해야 할 기존 application DB를 만든다."""

    engine = make_async_engine(normalize_async_dsn(dsn), pool_size=1)
    try:
        async with engine.begin() as connection:
            for statement in (
                "CREATE SCHEMA IF NOT EXISTS feature",
                "CREATE SCHEMA IF NOT EXISTS provider_sync",
                "CREATE SCHEMA IF NOT EXISTS ops",
                "CREATE TABLE IF NOT EXISTS ops.legacy_queue ("
                "  queue_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
                "  payload text NOT NULL"
                ")",
                "CREATE TABLE IF NOT EXISTS feature.legacy_rows ("
                "  row_id serial PRIMARY KEY,"
                "  name text NOT NULL"
                ")",
                "CREATE VIEW feature.legacy_view AS SELECT row_id FROM feature.legacy_rows",
                "INSERT INTO ops.legacy_queue (payload) VALUES ('seed')",
                "INSERT INTO feature.legacy_rows (name) VALUES ('seed')",
                "CREATE TABLE IF NOT EXISTS public.alembic_version ("
                "  version_num varchar(32) NOT NULL PRIMARY KEY"
                ")",
                "INSERT INTO public.alembic_version (version_num) VALUES ('0236') "
                "ON CONFLICT DO NOTHING",
            ):
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _snapshot(dsn: str) -> dict[str, object]:
    """bootstrap guard 전후에 같아야 하는 DB/cluster-visible 상태를 고정한다."""

    engine = make_async_engine(normalize_async_dsn(dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            database_owner = str(
                await connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_userbyid(datdba) "
                        "FROM pg_catalog.pg_database WHERE datname = current_database()"
                    )
                )
            )
            relations = {
                str(row.qualified): (str(row.relkind), str(row.owner))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT namespace.nspname || '.' || object.relname AS qualified, "
                            "object.relkind, pg_catalog.pg_get_userbyid(object.relowner) AS owner "
                            "FROM pg_catalog.pg_class AS object "
                            "JOIN pg_catalog.pg_namespace AS namespace "
                            "ON namespace.oid = object.relnamespace "
                            "WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops', 'public') "
                            "AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
                            "ORDER BY 1"
                        )
                    )
                ).mappings()
            }
            schemas = {
                str(row.nspname): (str(row.owner), str(row.nspacl or ""))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT namespace.nspname, "
                            "pg_catalog.pg_get_userbyid(namespace.nspowner) AS owner, "
                            "namespace.nspacl "
                            "FROM pg_catalog.pg_namespace AS namespace "
                            "WHERE namespace.nspname !~ '^pg_' "
                            "AND namespace.nspname <> 'information_schema' "
                            "ORDER BY 1"
                        )
                    )
                ).mappings()
            }
            default_acls = [
                (
                    str(row.role_name),
                    str(row.schema_name),
                    str(row.defaclobjtype),
                    str(row.defaclacl or ""),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT defaclrole::regrole::text AS role_name, "
                            "coalesce(defaclnamespace::regnamespace::text, '<global>') AS schema_name, "
                            "defaclobjtype, defaclacl::text AS defaclacl "
                            "FROM pg_catalog.pg_default_acl ORDER BY 1, 2, 3, 4"
                        )
                    )
                ).mappings()
            ]
            extensions = [
                (str(row.extname), str(row.nspname))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT extension.extname, namespace.nspname "
                            "FROM pg_catalog.pg_extension AS extension "
                            "JOIN pg_catalog.pg_namespace AS namespace "
                            "ON namespace.oid = extension.extnamespace "
                            "ORDER BY 1"
                        )
                    )
                ).mappings()
            ]
            has_alembic_version = bool(
                await connection.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
            )
            alembic_versions = (
                list(
                    (
                        await connection.scalars(
                            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                        )
                    ).all()
                )
                if has_alembic_version
                else []
            )
            roles = [
                (
                    str(row.rolname),
                    bool(row.rolcanlogin),
                    bool(row.rolsuper),
                    bool(row.rolinherit),
                    bool(row.rolcreaterole),
                    bool(row.rolcreatedb),
                    bool(row.rolreplication),
                    bool(row.rolbypassrls),
                    int(row.rolconnlimit),
                    str(row.rolvaliduntil),
                    tuple(row.rolconfig or []),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT rolname, rolcanlogin, rolsuper, rolinherit, rolcreaterole, "
                            "rolcreatedb, rolreplication, rolbypassrls, rolconnlimit, rolvaliduntil, rolconfig "
                            "FROM pg_catalog.pg_roles "
                            "WHERE rolname LIKE 'ktm\\_%' ESCAPE '\\' ORDER BY rolname"
                        )
                    )
                ).mappings()
            ]
            memberships = [
                (
                    str(row.granted),
                    str(row.member),
                    bool(row.admin_option),
                    bool(row.inherit_option),
                    bool(row.set_option),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT granted.rolname AS granted, member.rolname AS member, "
                            "membership.admin_option, membership.inherit_option, membership.set_option "
                            "FROM pg_catalog.pg_auth_members AS membership "
                            "JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname LIKE 'ktm\\_%' ESCAPE '\\' "
                            "OR member.rolname LIKE 'ktm\\_%' ESCAPE '\\' "
                            "ORDER BY 1, 2"
                        )
                    )
                ).mappings()
            ]
            database_settings = [
                (int(row.setrole), tuple(row.setconfig or []))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT setting.setrole, setting.setconfig "
                            "FROM pg_catalog.pg_db_role_setting AS setting "
                            "JOIN pg_catalog.pg_database AS database "
                            "ON database.oid = setting.setdatabase "
                            "WHERE database.datname = current_database() "
                            "ORDER BY setting.setrole"
                        )
                    )
                ).mappings()
            ]
    finally:
        await engine.dispose()
    return {
        "database_owner": database_owner,
        "relations": relations,
        "schemas": schemas,
        "default_acls": default_acls,
        "extensions": extensions,
        "alembic_versions": alembic_versions,
        "roles": roles,
        "memberships": memberships,
        "database_settings": database_settings,
    }


def _run_bootstrap(command: list[str]) -> subprocess.CompletedProcess[str]:
    """blocking 실행을 worker thread로 분리한다(ASYNC221)."""

    return subprocess.run(  # noqa: S603 - 저장소 스크립트를 그대로 검증한다
        command, check=False, capture_output=True, text=True
    )


async def _recreate_fresh_target(pg_container: Any) -> tuple[str, list[str], str]:
    """fresh target와 container-internal bootstrap 명령을 만든다."""

    raw_dsn = pg_container.get_connection_url()
    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'))
            await autocommit.execute(text(f'CREATE DATABASE "{_DATABASE}"'))
    finally:
        await admin_engine.dispose()

    from sqlalchemy.engine import make_url

    bootstrap_user = make_url(raw_dsn).username
    assert bootstrap_user is not None
    target_dsn = _sync_dsn(raw_dsn, _DATABASE)
    container_id = pg_container.get_wrapped_container().id
    container_dsn = target_dsn.replace(
        f":{pg_container.get_exposed_port(5432)}/", ":5432/"
    ).replace(pg_container.get_container_host_ip(), "127.0.0.1")
    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - DB 컨테이너 안에서 저장소 shell script를 실행한다
        ["docker", "cp", str(_SCRIPT), f"{container_id}:/tmp/bootstrap.sh"],
        check=True,
        capture_output=True,
    )
    command = [
        "docker",
        "exec",
        *(
            arg
            for key, value in (
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED", "true"),
                ("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", container_dsn),
                ("KOR_TRAVEL_MAP_MIGRATOR_PASSWORD", "bootstrap-probe-migrator"),
                ("KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD", "bootstrap-probe-api"),
                ("KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD", "bootstrap-probe-dagster"),
                ("KOR_TRAVEL_MAP_POSTGRES_DB", _DATABASE),
                ("KOR_TRAVEL_MAP_POSTGRES_USER", bootstrap_user),
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE", _DATABASE),
            )
            for arg in ("-e", f"{key}={value}")
        ),
        container_id,
        "sh",
        "/tmp/bootstrap.sh",
    ]
    return target_dsn, command, raw_dsn


async def _drop_target_and_roles(raw_dsn: str, roles: tuple[str, ...] = ()) -> None:
    """test가 만든 fresh DB와 cluster role을 회수한다."""

    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'))
            for role in roles:
                await autocommit.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
    finally:
        await admin_engine.dispose()


@pytest.mark.integration
async def test_bootstrap_rejects_existing_application_db_before_any_mutation(
    pg_container: Any,
) -> None:
    raw_dsn = pg_container.get_connection_url()
    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'))
            await autocommit.execute(text(f'CREATE DATABASE "{_DATABASE}"'))
    finally:
        await admin_engine.dispose()

    target_dsn = _sync_dsn(raw_dsn, _DATABASE)
    await _seed_existing_objects(target_dsn)
    before = await _snapshot(target_dsn)

    from sqlalchemy.engine import make_url

    bootstrap_user = make_url(raw_dsn).username
    assert bootstrap_user is not None
    container_id = pg_container.get_wrapped_container().id
    container_dsn = _sync_dsn(raw_dsn, _DATABASE).replace(
        f":{pg_container.get_exposed_port(5432)}/", ":5432/"
    ).replace(pg_container.get_container_host_ip(), "127.0.0.1")
    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - DB 컨테이너 안에서 저장소 shell script를 실행한다
        ["docker", "cp", str(_SCRIPT), f"{container_id}:/tmp/bootstrap.sh"],
        check=True,
        capture_output=True,
    )
    bootstrap_command = [
        "docker",
        "exec",
        *(
            arg
            for key, value in (
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED", "true"),
                ("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", container_dsn),
                ("KOR_TRAVEL_MAP_MIGRATOR_PASSWORD", "bootstrap-probe-migrator"),
                ("KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD", "bootstrap-probe-api"),
                ("KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD", "bootstrap-probe-dagster"),
                ("KOR_TRAVEL_MAP_POSTGRES_DB", _DATABASE),
                ("KOR_TRAVEL_MAP_POSTGRES_USER", bootstrap_user),
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE", _DATABASE),
            )
            for arg in ("-e", f"{key}={value}")
        ),
        container_id,
        "sh",
        "/tmp/bootstrap.sh",
    ]
    result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

    assert result.returncode != 0
    assert "baseline-300 bootstrap requires a fresh DB" in result.stderr
    assert await _snapshot(target_dsn) == before


@pytest.mark.integration
async def test_bootstrap_rolls_back_all_mutation_when_existing_membership_is_unsafe(
    pg_container: Any,
) -> None:
    """late role graph rejection도 password/role/DB state를 남기지 않는다."""

    roles = ("ktm_feature_schema_owner", "ktm_feature_migrator")
    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text("CREATE ROLE ktm_feature_schema_owner NOLOGIN NOINHERIT")
            )
            await autocommit.execute(
                text("CREATE ROLE ktm_feature_migrator LOGIN NOINHERIT PASSWORD 'pre-bootstrap'")
            )
            await autocommit.execute(
                text(
                    "GRANT ktm_feature_schema_owner TO ktm_feature_migrator "
                    "WITH ADMIN TRUE, INHERIT FALSE, SET TRUE"
                )
            )
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "unexpected application role membership edge" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, roles)


@pytest.mark.integration
async def test_bootstrap_rejects_precreated_application_schema_acl_before_mutation(
    pg_container: Any,
) -> None:
    """빈 schema의 foreign ACL/default ACL도 canonical fresh bootstrap 입력이 아니다."""

    role = "ktm_bootstrap_foreign_principal"
    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await autocommit.execute(text("CREATE SCHEMA feature"))
            await autocommit.execute(text(f"GRANT USAGE, CREATE ON SCHEMA feature TO {role}"))
            await autocommit.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA feature "
                    f"GRANT SELECT ON TABLES TO {role}"
                )
            )
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "application schemas exist" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, (role,))


@pytest.mark.integration
async def test_bootstrap_creates_extensions_in_x_extension_on_stock_virgin_postgis(
    pg_container: Any,
) -> None:
    """공식 빈 PostGIS image도 baseline-300 bootstrap으로만 준비한다.

    테스트 fixture가 미리 extension을 만들거나 public extension을 삭제하면 실제 fresh
    deployment 경로를 검증하지 못한다. 이 test는 새 database에서 role bootstrap만
    실행하고, `postgis`/`pg_trgm`/`pgcrypto`가 모두 ADR-008 위치에 생성되는지 확인한다.
    """

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    created_roles: tuple[str, ...] = ()
    try:
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode == 0, result.stderr
        async with engine.connect() as connection:
            extensions = {
                str(row.extname): str(row.nspname)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT extension.extname, namespace.nspname "
                            "FROM pg_catalog.pg_extension AS extension "
                            "JOIN pg_catalog.pg_namespace AS namespace "
                            "ON namespace.oid = extension.extnamespace "
                            "WHERE extension.extname IN ('postgis', 'pg_trgm', 'pgcrypto')"
                        )
                    )
                ).mappings()
            }
            assert extensions == {
                "postgis": "x_extension",
                "pg_trgm": "x_extension",
                "pgcrypto": "x_extension",
            }
            assert (
                await connection.scalar(text("SELECT to_regclass('public.alembic_version') IS NULL"))
            ) is True
            created_roles = tuple(
                str(role)
                for role in (
                    await connection.scalars(
                        text(
                            "SELECT rolname FROM pg_catalog.pg_roles "
                            "WHERE rolname LIKE 'ktm\\_%' ESCAPE '\\' ORDER BY rolname"
                        )
                    )
                ).all()
            )
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, created_roles)


@pytest.mark.integration
async def test_bootstrap_rolls_back_all_mutation_when_extension_schema_is_wrong(
    pg_container: Any,
) -> None:
    """사전 public PostGIS DB는 fresh로 간주하지 않고 원자적으로 거부한다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("CREATE EXTENSION postgis WITH SCHEMA public"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "requires postgis in x_extension" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)
