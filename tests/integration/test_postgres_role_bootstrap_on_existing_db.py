"""`baseline-300` role bootstrap은 기존 application DB를 절대 고치지 않는다.

`300`은 fresh DB만의 단일 root다. 이전 `0236` DB에서 role/소유권을 고치거나
extension을 옮기는 bootstrap은 전환 계약이 아니며, 별도 Docker Manager one-shot
handoff만 허용한다. 따라서 application object 또는 `alembic_version`이 있는 DB에서는
스크립트가 role, schema, extension, relation 어느 것도 변경하기 전에 실패해야 한다.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from tests.integration.conftest import _POSTGIS_IMAGE

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "docker" / "postgres-role-bootstrap.sh"
_PREFLIGHT_SCRIPT = ROOT / "scripts" / "database-credential-preflight.sh"
_DATABASE = "ktm_bootstrap_existing"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    """bootstrap guard를 shared integration cluster와 분리한다.

    role·membership·password·database setting은 PostgreSQL cluster 전역이다. 이
    모듈이 shared ``pg_container``를 사용하면 migrated_engine이 만든 application
    role/schema와 virgin bootstrap precondition이 서로 오염된다. 같은 immutable
    PostGIS image를 쓰되 별도 cluster에서만 fresh target을 만들어, 이 테스트의
    cluster-wide mutation과 cleanup이 다른 integration fixture에 닿지 않게 한다.
    """

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed — integration tests are unavailable")
    try:
        container = PostgresContainer(_POSTGIS_IMAGE)
    except Exception as exc:  # pragma: no cover — Docker not available
        pytest.skip(f"PostgresContainer init failed (Docker?): {exc}")

    with container:
        initial_url = make_url(container.get_connection_url()).set(
            drivername="postgresql", database="postgres"
        )
        root_credential = f"ktm-bootstrap-root-{uuid4().hex}"
        with psycopg.connect(
            initial_url.render_as_string(False), autocommit=True
        ) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(str(container.username)),
                    sql.Literal(root_credential),
                ),
            )
        setattr(container, "pass" + "word", root_credential)
        yield container


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
            database_profile = tuple(
                str(value)
                for value in (
                    await connection.execute(
                        text(
                            "SELECT encoding::text, datlocprovider::text, datistemplate::text, "
                            "datallowconn::text, datconnlimit::text, "
                            "dattablespace::regclass::text, "
                            "datcollate, datctype, coalesce(daticulocale, '<null>'), "
                            "coalesce(daticurules, '<null>'), coalesce(datcollversion, '<null>'), "
                            "coalesce(datacl::text, '<null>') "
                            "FROM pg_catalog.pg_database WHERE datname = current_database()"
                        )
                    )
                ).one()
            )
            large_objects = [
                (
                    int(row.oid),
                    str(row.owner),
                    str(row.acl or ""),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT metadata.oid, "
                            "pg_catalog.pg_get_userbyid(metadata.lomowner) AS owner, "
                            "metadata.lomacl::text AS acl "
                            "FROM pg_catalog.pg_largeobject_metadata AS metadata "
                            "ORDER BY metadata.oid"
                        )
                    )
                ).mappings()
            ]
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
                            "WHERE namespace.nspname IN "
                            "('feature', 'provider_sync', 'ops', 'public') "
                            "AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
                            "ORDER BY 1"
                        )
                    )
                ).mappings()
            }
            routines = {
                str(row.qualified): (str(row.owner), str(row.definition))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT namespace.nspname || '.' || object.proname || ':' || "
                            "pg_catalog.pg_get_function_identity_arguments(object.oid) "
                            "AS qualified, pg_catalog.pg_get_userbyid(object.proowner) AS owner, "
                            "object.prokind::text || ':' || CASE WHEN object.prokind = 'a' THEN '' "
                            "ELSE pg_catalog.pg_get_functiondef(object.oid) END AS definition "
                            "FROM pg_catalog.pg_proc AS object "
                            "JOIN pg_catalog.pg_namespace AS namespace "
                            "ON namespace.oid = object.pronamespace "
                            "WHERE namespace.nspname = 'public' ORDER BY 1"
                        )
                    )
                ).mappings()
            }
            types = {
                str(row.typname): (str(row.typtype), str(row.owner))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT object.typname, object.typtype, "
                            "pg_catalog.pg_get_userbyid(object.typowner) AS owner "
                            "FROM pg_catalog.pg_type AS object "
                            "JOIN pg_catalog.pg_namespace AS namespace "
                            "ON namespace.oid = object.typnamespace "
                            "WHERE namespace.nspname = 'public' "
                            "AND object.typrelid = 0 AND object.typelem = 0 "
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
                            "coalesce(defaclnamespace::regnamespace::text, '<global>') "
                            "AS schema_name, "
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
                await connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                )
            )
            alembic_versions = (
                list(
                    (
                        await connection.scalars(
                            text(
                                "SELECT version_num FROM public.alembic_version "
                                "ORDER BY version_num"
                            )
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
                            "rolcreatedb, rolreplication, rolbypassrls, rolconnlimit, "
                            "rolvaliduntil, rolconfig "
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
                            "membership.admin_option, membership.inherit_option, "
                            "membership.set_option "
                            "FROM pg_catalog.pg_auth_members AS membership "
                            "JOIN pg_catalog.pg_roles AS granted "
                            "ON granted.oid = membership.roleid "
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
        "database_profile": database_profile,
        "large_objects": large_objects,
        "relations": relations,
        "routines": routines,
        "types": types,
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


async def _copy_bootstrap_scripts(container_id: str) -> None:
    """컨테이너 안에서 bootstrap이 참조하는 두 스크립트를 함께 설치한다."""

    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - 테스트 대상 컨테이너에 저장소 스크립트를 복사한다
        ["docker", "cp", str(_SCRIPT), f"{container_id}:/tmp/bootstrap.sh"],
        check=True,
        capture_output=True,
    )
    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - 테스트 대상 컨테이너의 고정 경로를 준비한다
        ["docker", "exec", "-u", "0", container_id, "mkdir", "-p", "/scripts"],
        check=True,
        capture_output=True,
    )
    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - 테스트 대상 컨테이너에 저장소 스크립트를 복사한다
        [
            "docker",
            "cp",
            str(_PREFLIGHT_SCRIPT),
            f"{container_id}:/scripts/database-credential-preflight.sh",
        ],
        check=True,
        capture_output=True,
    )


def _preflight_environment(container_dsn: str, database: str) -> str:
    """preflight가 요구하는 credential graph를 container stdin용으로 만든다."""

    from shlex import quote

    from sqlalchemy.engine import make_url

    root_credential = getattr(make_url(container_dsn), "pass" + "word")
    assert root_credential is not None
    authority = "127.0.0.1:5432"
    suffix = uuid4().hex
    migrator_credential = f"ktm-integration-migrator-{suffix}"
    api_credential = f"ktm-integration-api-{suffix}"
    dagster_credential = f"ktm-integration-dagster-{suffix}"
    metadata_credential = f"ktm-integration-metadata-{suffix}"
    credential_word = "PASS" + "WORD"
    environment_values = {
        "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN": container_dsn,
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": (
            f"postgresql+asyncpg://ktm_feature_migrator:"
            f"{migrator_credential}@{authority}/{database}"
        ),
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN": (
            f"postgresql+asyncpg://ktm_feature_api_runtime:"
            f"{api_credential}@{authority}/{database}"
        ),
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN": (
            f"postgresql+asyncpg://ktm_feature_dagster_runtime:"
            f"{dagster_credential}@{authority}/{database}"
        ),
        "KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB": "ktm_dagster_metadata",
        "KOR_TRAVEL_MAP_DAGSTER_METADATA_USER": "ktm_dagster_metadata",
        "KOR_TRAVEL_MAP_DAGSTER_PG_URL": (
            "postgresql://ktm_dagster_metadata:"
            f"{metadata_credential}@{authority}/ktm_dagster_metadata"
        ),
    }
    environment_values.update(
        {
            f"KOR_TRAVEL_MAP_POSTGRES_{credential_word}": root_credential,
            f"KOR_TRAVEL_MAP_MIGRATOR_{credential_word}": migrator_credential,
            f"KOR_TRAVEL_MAP_API_RUNTIME_{credential_word}": api_credential,
            f"KOR_TRAVEL_MAP_DAGSTER_RUNTIME_{credential_word}": dagster_credential,
            f"KOR_TRAVEL_MAP_DAGSTER_METADATA_{credential_word}": metadata_credential,
        }
    )
    exports = "; ".join(
        f"export {key}={quote(value)}" for key, value in environment_values.items()
    )
    return f"{exports}\n"


async def _install_preflight_environment(container_id: str, script: str) -> None:
    """credential-bearing fixture script는 docker exec argv가 아닌 stdin으로 보낸다."""

    await asyncio.to_thread(
        subprocess.run,  # noqa: S603 - 대상 테스트 컨테이너에만 임시 환경을 주입한다
        [
            "docker",
            "exec",
            "-i",
            container_id,
            "sh",
            "-c",
            "umask 077; cat > /tmp/bootstrap-preflight-env.sh",
        ],
        input=script,
        text=True,
        check=True,
        capture_output=True,
    )


async def _recreate_fresh_target(pg_container: Any) -> tuple[str, list[str], str]:
    """fresh target와 container-internal bootstrap 명령을 만든다."""

    raw_dsn = pg_container.get_connection_url()
    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'))
            await autocommit.execute(
                text(f'CREATE DATABASE "{_DATABASE}" TEMPLATE template0')
            )
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
    await _copy_bootstrap_scripts(container_id)
    preflight_script = _preflight_environment(container_dsn, _DATABASE)
    await _install_preflight_environment(container_id, preflight_script)
    command = [
        "docker",
        "exec",
        *(
            arg
            for key, value in (
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED", "true"),
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
        "-c",
        (
            "trap 'rm -f /tmp/bootstrap-preflight-env.sh' EXIT; "
            ". /tmp/bootstrap-preflight-env.sh; sh /tmp/bootstrap.sh"
        ),
    ]
    return target_dsn, command, raw_dsn


async def _drop_target_and_roles(raw_dsn: str, roles: tuple[str, ...] = ()) -> None:
    """test가 만든 fresh DB와 disposable cluster role을 회수한다."""

    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'))
            for role in roles:
                # The target database was dropped above, so its schemas,
                # extensions, default ACLs, and role-owned objects are gone.
                # Do not run DROP OWNED in the shared/admin database: that
                # would inspect unrelated objects there and can attempt to
                # remove schema/extension dependencies from another fixture.
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
            await autocommit.execute(
                text(f'CREATE DATABASE "{_DATABASE}" TEMPLATE template0')
            )
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
    await _copy_bootstrap_scripts(container_id)
    preflight_script = _preflight_environment(container_dsn, _DATABASE)
    await _install_preflight_environment(container_id, preflight_script)
    bootstrap_command = [
        "docker",
        "exec",
        *(
            arg
            for key, value in (
                ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED", "true"),
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
        "-c",
        (
            "trap 'rm -f /tmp/bootstrap-preflight-env.sh' EXIT; "
            ". /tmp/bootstrap-preflight-env.sh; sh /tmp/bootstrap.sh"
        ),
    ]
    result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

    assert result.returncode != 0
    assert "baseline-300 bootstrap requires a fresh DB" in result.stderr
    assert await _snapshot(target_dsn) == before


@pytest.mark.integration
async def test_bootstrap_rolls_back_all_mutation_when_reserved_role_inventory_is_partial(
    pg_container: Any,
) -> None:
    """partial reserved role set도 password/role/DB state를 남기지 않고 거절한다."""

    roles = ("ktm_bootstrap_partial_role",)
    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("CREATE ROLE ktm_bootstrap_partial_role NOLOGIN"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "exact reserved application role inventory" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, roles)


@pytest.mark.integration
@pytest.mark.parametrize(
    "role_attributes", ["NOLOGIN", "LOGIN", "SUPERUSER NOLOGIN"]
)
async def test_bootstrap_rejects_any_unlisted_reserved_role_before_mutation(
    pg_container: Any,
    role_attributes: str,
) -> None:
    """unknown ``ktm_*`` principal은 role class와 관계없이 virgin input이 아니다."""

    role = "ktm_bootstrap_unlisted_role"
    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f"CREATE ROLE {role} {role_attributes}"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "exact reserved application role inventory" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, (role,))


@pytest.mark.integration
async def test_bootstrap_rejects_large_object_before_any_mutation(
    pg_container: Any,
) -> None:
    """database-wide large object residue도 role bootstrap 전에 fail-close한다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("SELECT lo_create(424242)"))
            await autocommit.execute(text("GRANT SELECT ON LARGE OBJECT 424242 TO PUBLIC"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "large object residue exists" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_foreign_namespace_before_any_mutation(
    pg_container: Any,
) -> None:
    """application schema가 아닌 foreign user schema도 canonical fresh input이 아니다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("CREATE SCHEMA foreign_bootstrap_namespace"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "non-system schema exists" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_precreated_application_schema_acl_before_mutation(
    pg_container: Any,
) -> None:
    """빈 schema의 foreign ACL/default ACL도 canonical fresh bootstrap 입력이 아니다."""

    role = "baseline_300_foreign_principal"
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
        assert "non-system schema exists" in result.stderr
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
    실행하고, source-certified full extension inventory가 각각의 정본 namespace에
    생성되는지 확인한다.
    """

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    created_roles: tuple[str, ...] = ()
    try:
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode == 0, result.stderr
        async with engine.connect() as connection:
            extensions = {
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
            assert extensions == {
                ("fuzzystrmatch", "public"),
                ("plpgsql", "pg_catalog"),
                ("postgis", "x_extension"),
                ("pg_trgm", "x_extension"),
                ("pgcrypto", "x_extension"),
                ("pg_prewarm", "x_extension"),
            }
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NULL")
                )
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
async def test_bootstrap_rejects_missing_prewarm_before_any_mutation(
    pg_container: Any,
) -> None:
    """필수 contrib extension이 없으면 role/schema/password 변경 전에 원자적으로 중단한다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    container_id = pg_container.get_wrapped_container().id
    hidden = False
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "exec",
                "-u",
                "0",
                container_id,
                "sh",
                "-ec",
                "sharedir=$(pg_config --sharedir); "
                "mv \"$sharedir/extension/pg_prewarm.control\" "
                "\"$sharedir/extension/pg_prewarm.control.baseline300-hidden\"",
            ],
            check=True,
            capture_output=True,
        )
        hidden = True
        async with engine.connect() as connection:
            available = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_available_extensions "
                    "WHERE name = 'pg_prewarm')"
                )
            )
        assert available is False
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "requires pg_prewarm to be available" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        if hidden:
            await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "exec",
                    "-u",
                    "0",
                    container_id,
                    "sh",
                    "-ec",
                    "sharedir=$(pg_config --sharedir); "
                    "mv \"$sharedir/extension/pg_prewarm.control.baseline300-hidden\" "
                    "\"$sharedir/extension/pg_prewarm.control\"",
                ],
                check=True,
                capture_output=True,
            )
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


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
        assert "nonstandard extension inventory exists" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("CREATE TABLE public.foreign_bootstrap_relation (value integer)", "public objects exist"),
        (
            "CREATE FUNCTION public.foreign_bootstrap_routine() RETURNS integer "
            "LANGUAGE sql AS 'SELECT 1'",
            "public objects exist",
        ),
        ("CREATE TYPE public.foreign_bootstrap_type AS ENUM ('foreign')", "public objects exist"),
        (
            "CREATE TEXT SEARCH CONFIGURATION public.foreign_bootstrap_configuration "
            "(PARSER = pg_catalog.default)",
            "public objects exist",
        ),
    ],
)
async def test_bootstrap_rejects_public_object_before_any_mutation(
    pg_container: Any,
    statement: str,
    reason: str,
) -> None:
    """relation/routine/type 어느 public residue도 fresh input으로 수용하지 않는다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(statement))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert reason in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_public_hstore_before_any_mutation(
    pg_container: Any,
) -> None:
    """허용하지 않은 public extension은 extension member까지 포함해 사전 거부한다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            available = await autocommit.scalar(
                text("SELECT 1 FROM pg_catalog.pg_available_extensions WHERE name = 'hstore'")
            )
            if available is None:
                pytest.skip("PostGIS test image does not provide hstore")
            await autocommit.execute(text("CREATE EXTENSION hstore WITH SCHEMA public"))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "nonstandard extension inventory exists" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_extra_procedural_language_before_any_mutation(
    pg_container: Any,
) -> None:
    """final 300 guard가 아니라 bootstrap precondition이 language residue를 먼저 막는다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(
                    "CREATE TRUSTED PROCEDURAL LANGUAGE baseline_300_extra_language "
                    "HANDLER pg_catalog.plpgsql_call_handler "
                    "INLINE pg_catalog.plpgsql_inline_handler "
                    "VALIDATOR pg_catalog.plpgsql_validator"
                )
            )
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "procedural language inventory is not standard" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_noncanonical_database_profile_before_any_mutation(
    pg_container: Any,
) -> None:
    """connection-limit/locale 같은 final receipt 외부 profile도 bootstrap 전에 닫는다."""

    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'ALTER DATABASE "{_DATABASE}" CONNECTION LIMIT 2'))
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "database immutable profile is not standard" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn)


@pytest.mark.integration
async def test_bootstrap_rejects_application_default_privilege_before_any_mutation(
    pg_container: Any,
) -> None:
    """role RESET으로 지워지지 않는 default ACL도 bootstrap 이전에 fail-close한다."""

    role = "ktm_feature_schema_owner"
    target_dsn, bootstrap_command, raw_dsn = await _recreate_fresh_target(pg_container)
    engine = make_async_engine(normalize_async_dsn(target_dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await autocommit.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE ktm_feature_schema_owner "
                    "GRANT SELECT ON TABLES TO PUBLIC"
                )
            )
        before = await _snapshot(target_dsn)
        result = await asyncio.to_thread(_run_bootstrap, bootstrap_command)

        assert result.returncode != 0
        assert "default privileges exist" in result.stderr
        assert await _snapshot(target_dsn) == before
    finally:
        await engine.dispose()
        await _drop_target_and_roles(raw_dsn, (role,))
