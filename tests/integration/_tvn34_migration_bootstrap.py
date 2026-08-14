"""자체적으로 DB를 만들어 마이그레이션하는 통합 테스트가 공유하는 bootstrap.

0095는 restricted migrator가 state/audit routine owner membership을 **스스로**
부여하지 않는지 검증한다. 그래서 fresh DB에 ``alembic upgrade``를 걸려면 배포
bootstrap과 같은 선행조건이 먼저 있어야 한다. conftest의 ``migrated_engine``은
그것을 하고 있었지만, 자기 DB를 따로 만드는 테스트들(alembic upgrade / uuid shadow /
metadata consistency / legacy write fence)은 빠뜨려서 fixture 단계에서
``0095 requires bootstrap membership of schema owner in state/audit owners``로
통째로 죽었다. 같은 코드를 두 벌 두면 또 갈리므로 한 곳에 둔다.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_TVN34_TEST_MIGRATOR_PASSWORD = "tvn34-test-only-migrator-password"


async def bootstrap_tvn34_migration_roles(engine: AsyncEngine) -> str:
    """실 bootstrap와 같은 principal graph를 fresh test DB에 먼저 만든다.

    0095는 restricted migrator가 state/audit routine owner membership을 스스로
    부여하지 않는다는 것을 검증한다. 따라서 일반 ``alembic upgrade`` fixture도
    deployment bootstrap와 같은 선행조건을 명시적으로 재현해야 한다. 이 helper는
    disposable PostGIS DB에서만 호출되며 LOGIN password는 testcontainer 전용이다.
    """
    from sqlalchemy import text

    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                DO $roles$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = 'ktm_feature_schema_owner'
                    ) THEN
                        CREATE ROLE ktm_feature_schema_owner NOLOGIN NOINHERIT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = 'ktm_feature_state_procedure_owner'
                    ) THEN
                        CREATE ROLE ktm_feature_state_procedure_owner NOLOGIN NOINHERIT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = 'ktm_feature_audit_writer'
                    ) THEN
                        CREATE ROLE ktm_feature_audit_writer NOLOGIN NOINHERIT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = 'ktm_feature_runtime'
                    ) THEN
                        CREATE ROLE ktm_feature_runtime NOLOGIN NOINHERIT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = 'ktm_feature_migrator'
                    ) THEN
                        CREATE ROLE ktm_feature_migrator LOGIN NOINHERIT
                            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
                            NOREPLICATION PASSWORD 'tvn34-test-only-migrator-password';
                    END IF;
                END
                $roles$;
                """
            )
        )
        for statement in (
            "ALTER ROLE ktm_feature_migrator LOGIN NOINHERIT "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION "
            "PASSWORD 'tvn34-test-only-migrator-password'",
            "GRANT ktm_feature_schema_owner TO ktm_feature_migrator "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
            "GRANT ktm_feature_state_procedure_owner TO ktm_feature_schema_owner "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
            "GRANT ktm_feature_audit_writer TO ktm_feature_schema_owner "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE",
            "CREATE SCHEMA IF NOT EXISTS feature AUTHORIZATION ktm_feature_schema_owner",
            "CREATE SCHEMA IF NOT EXISTS provider_sync AUTHORIZATION ktm_feature_schema_owner",
            "CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION ktm_feature_schema_owner",
            "CREATE SCHEMA IF NOT EXISTS x_extension AUTHORIZATION ktm_feature_schema_owner",
            # `IF NOT EXISTS`는 schema가 이미 있으면 **AUTHORIZATION을 적용하지 않는다.**
            # 같은 DB에서 `pg_engine`이 먼저 서면 4개 schema가 컨테이너 superuser 소유로
            # 굳고, 뒤이어 배포 경로(migrator → SET ROLE schema owner)로 도는 migration이
            # `permission denied for schema feature`로 죽는다. 누가 먼저 만들었든
            # bootstrap이 소유권을 **확정**하게 해서 순서 결합을 없앤다.
            "ALTER SCHEMA feature OWNER TO ktm_feature_schema_owner",
            "ALTER SCHEMA provider_sync OWNER TO ktm_feature_schema_owner",
            "ALTER SCHEMA ops OWNER TO ktm_feature_schema_owner",
            "ALTER SCHEMA x_extension OWNER TO ktm_feature_schema_owner",
            "GRANT USAGE, CREATE ON SCHEMA feature "
            "TO ktm_feature_state_procedure_owner, ktm_feature_audit_writer",
            # x_extension USAGE는 런타임 필수다 — 없으면 runtime의 평범한 core
            # update SQL도 typed coordinate expression parse에서 죽는다. 체인에서는
            # `0095`가 줬지만 squash baseline은 3개 스키마만 재현한다. 정본은
            # `docker/postgres-role-bootstrap.sh`이고 여기는 그 거울이다 — 어긋나면
            # 통합 테스트만 통과하고 실제 배포가 깨지는 상태가 만들어진다.
            "GRANT USAGE ON SCHEMA x_extension "
            "TO ktm_feature_state_procedure_owner, ktm_feature_runtime",
        ):
            await connection.execute(text(statement))
        # PostGIS image가 initdb에서 public에 둔 non-relocatable extension은
        # application relation이 없는 fresh DB에서만 다시 만든다. 이것은 production
        # bootstrap의 destructive-operation guard와 같은 fresh-only branch다.
        #
        # 주석만 있고 **검사는 없었다.** 이 helper가 conftest 전용이던 동안은 대상이
        # 항상 fresh DB라 드러나지 않았지만, 공유 helper가 되자마자
        # `test_alembic_upgrade`가 컨테이너의 **공유 기본 DB**에 이것을 걸어
        # postgis를 CASCADE로 날렸고 뒤따르는 테스트 수십 건이 무너졌다
        # (2026-08-12 실측). 전제를 주석이 아니라 코드로 강제한다.
        application_relation_count = int(
            (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_class AS c "
                        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                        "WHERE c.relkind IN ('r', 'p', 'v', 'm') "
                        "AND n.nspname IN ('feature', 'provider_sync', 'ops')"
                    )
                )
            ).scalar_one()
        )
        if application_relation_count == 0:
            await connection.execute(
                text("DROP EXTENSION IF EXISTS postgis_topology CASCADE")
            )
            await connection.execute(text("DROP EXTENSION IF EXISTS postgis CASCADE"))
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension")
            )
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA x_extension")
        )
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA x_extension")
        )
        database_name = str(
            (await connection.execute(text("SELECT current_database()"))).scalar_one()
        )
        quoted_database_name = '"' + database_name.replace('"', '""') + '"'
        await connection.execute(
            text(f"ALTER DATABASE {quoted_database_name} OWNER TO ktm_feature_schema_owner")
        )
    return _TVN34_TEST_MIGRATOR_PASSWORD


async def bootstrapped_migrator_dsn(async_dsn: str) -> str:
    """fresh DB에 principal graph를 만들고, **migrator 자격의 DSN**을 돌려준다.

    0095 이후 schema object의 owner는 ``ktm_feature_schema_owner``다. superuser로
    ``alembic upgrade``를 돌리면 0095의 bootstrap 검사는 지나가도 그 뒤 runtime ACL
    재조정이 ``permission denied for table feature_versions``로 죽는다 — superuser는
    owner가 아니고, 0097의 grant는 owner 자격에서만 성립하기 때문이다. 배포도
    migrator LOGIN → ``SET ROLE`` schema owner 경로로만 돈다(ADR-090).

    자기 DB를 따로 만드는 테스트가 이 한 줄만 쓰면 배포와 같은 경로가 된다.
    """

    from sqlalchemy.engine import make_url

    from kortravelmap.infra.db import make_async_engine

    bootstrap_engine = make_async_engine(async_dsn, pool_size=1)
    try:
        migrator_password = await bootstrap_tvn34_migration_roles(bootstrap_engine)
    finally:
        await bootstrap_engine.dispose()
    return (
        make_url(async_dsn)
        .set(username="ktm_feature_migrator", password=migrator_password)
        .render_as_string(hide_password=False)
    )


@contextlib.contextmanager
def alembic_schema_owner_role() -> Iterator[None]:
    """migration 동안 ``SET ROLE ktm_feature_schema_owner``를 켠다 (ADR-090).

    migrator LOGIN은 그 자체로는 아무것도 소유하지 않는다. 이 flag 없이 upgrade를
    돌리면 alembic이 ``public``에 version table을 만들려다
    ``permission denied for schema public``으로 죽는다 — schema owner로 전환해야
    ``pg_database_owner`` 경유 권한이 선다. conftest의 ``migrated_engine``은 이미
    이렇게 돌고 있었고, 자기 DB를 만드는 테스트만 빠져 있었다.
    """

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
