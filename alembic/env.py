"""Alembic env.py — async-compatible, SecretStr DSN injection (ADR-007).

DSN은 `KorTravelMapSettings.pg_dsn` (`KOR_TRAVEL_MAP_PG_DSN` env var)에서 읽는다.
asyncpg driver로 정규화 후 `AsyncEngine`을 만들어 마이그레이션 실행.

``infra/models.py``의 ``metadata``를 ``target_metadata``로 사용 — autogenerate
지원 (현 PR#28부터). search_path는 ``public, x_extension`` (ADR-008).

사용:
    KOR_TRAVEL_MAP_PG_DSN=postgresql://... alembic upgrade head
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic.script import ScriptDirectory
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from kortravelmap.infra.alembic_exclusions import (
    PENDING_MIGRATION_TABLES as _PENDING_MIGRATION_TABLES,
)
from kortravelmap.infra.alembic_exclusions import (
    PENDING_MIGRATION_TABLES_EXPIRE_AT as _PENDING_MIGRATION_TABLES_EXPIRE_AT,
)
from kortravelmap.infra.alembic_exclusions import (
    UNCOMPARED_INDEXES as _UNCOMPARED_INDEXES,
)
from kortravelmap.infra.alembic_exclusions import (
    UNMAPPED_APP_TABLES as _UNMAPPED_APP_TABLES,
)
from kortravelmap.infra.db import normalize_async_dsn
from kortravelmap.infra.models import metadata

if TYPE_CHECKING:
    pass

# Alembic Config — alembic.ini.
config = context.config

# Logging setup.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# DSN 결정 우선순위:
#   1. 호출자가 ``Config.set_main_option('sqlalchemy.url', ...)``로 주입한 값
#      (예: 테스트 ``alembic.command.upgrade`` 직접 호출 시)
#   2. ``KOR_TRAVEL_MAP_PG_DSN`` env var (`KorTravelMapSettings.pg_dsn`)
# alembic.ini의 ``placeholder`` URL은 환경 미설정 fallback이며 항상 override.
_existing_url = config.get_main_option("sqlalchemy.url")
if not _existing_url or "placeholder" in _existing_url:
    from kortravelmap.settings import KorTravelMapSettings  # lazy import

    _settings = KorTravelMapSettings()
    _existing_url = normalize_async_dsn(_settings.pg_dsn.get_secret_value())
    config.set_main_option("sqlalchemy.url", _existing_url)
else:
    _existing_url = normalize_async_dsn(_existing_url)
    config.set_main_option("sqlalchemy.url", _existing_url)

# autogenerate 대상 metadata.
target_metadata = metadata

_FORWARD_ONLY_BOUNDARY = "0200_schema_baseline"
_USE_SCHEMA_OWNER_ROLE_ENV = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"

_METADATA_TABLE_IDENTITIES = frozenset(
    (table.schema, table.name) for table in target_metadata.tables.values()
)
_MISSING_PENDING_MIGRATION_TABLES = (
    _PENDING_MIGRATION_TABLES - _METADATA_TABLE_IDENTITIES
)
if _MISSING_PENDING_MIGRATION_TABLES:
    missing_names = ", ".join(
        f"{schema}.{table}"
        for schema, table in sorted(_MISSING_PENDING_MIGRATION_TABLES)
    )
    raise RuntimeError(
        "pending-migration table exclusions lack SQLAlchemy mappings: " + missing_names
    )
if _PENDING_MIGRATION_TABLES & _UNMAPPED_APP_TABLES:
    raise RuntimeError(
        "pending-migration tables must not also be unmapped-table exclusions"
    )
if any(
    revision.revision == _PENDING_MIGRATION_TABLES_EXPIRE_AT
    for revision in ScriptDirectory.from_config(config).walk_revisions()
):
    raise RuntimeError(
        "pending-migration table exclusions expired at "
        f"{_PENDING_MIGRATION_TABLES_EXPIRE_AT}; remove the ledger and Alembic filter"
    )


def _revisions_include_forward_only_boundary(
    script: ScriptDirectory,
    revisions: tuple[str, ...],
) -> bool:
    """revision 집합 또는 그 조상에 0200 squash 경계가 있는지 반환한다."""
    if not revisions:
        return False
    return any(
        node.revision == _FORWARD_ONLY_BOUNDARY
        for node in script.iterate_revisions(revisions, None, inclusive=True)
    )


def _guard_forward_only_target() -> None:
    """downgrade/stamp 계획이 0200 아래로 가면 첫 step 전에 거부한다."""
    migration_context = context.get_context()
    migration_fn = migration_context.opts.get("fn")
    if migration_fn is None or migration_fn.__name__ not in {
        "downgrade",
        "do_stamp",
    }:
        # upgrade는 경계를 내리지 않는다. current/check/autogenerate callback은
        # 여기서 실행하면 출력·reflection·hook이 두 번 실행되므로 건드리지 않는다.
        return

    current_heads = migration_context.get_current_heads()
    script = ScriptDirectory.from_config(config)
    destination = migration_context.opts.get("destination_rev")
    if migration_fn.__name__ == "downgrade":
        planned_steps = tuple(
            script._downgrade_revs(  # type: ignore[arg-type]  # noqa: SLF001
                destination,
                current_heads,
            )
        )
    else:
        # stamp --purge는 run_migrations()가 version table을 비운 뒤 callback을
        # 실행한다. guard는 purge 전 current head로 하향 경계만 판정하고 실제
        # callback은 Alembic이 정상 시점에 정확히 한 번 실행하게 둔다.
        planned_steps = tuple(
            script._stamp_revs(destination, current_heads)  # noqa: SLF001
        )
    crosses_boundary = any(
        step.is_downgrade
        and _revisions_include_forward_only_boundary(
            script,
            step.from_revisions_no_deps,
        )
        and not _revisions_include_forward_only_boundary(
            script,
            step.to_revisions_no_deps,
        )
        for step in planned_steps
    )
    if crosses_boundary:
        raise RuntimeError(
            "0200 is forward-only: recreate the application DB from the current "
            "baseline and reload provider inputs under a writer fence"
        )


# ``alembic check`` 정합 필터 (ADR-075 D-12-2, T-VN-19).
# ``include_schemas=True`` + ``compare_type`` 은 app schema 밖 객체와 아직 ORM
# 모델이 없는 app table까지 비교해 clean DB check 를 실패시킨다. 아래 3개 명시
# 목록만 비교에서 제외한다(blanket ignore 아님 — 이름을 전부 나열).
#
# 1) PostGIS/extension 소유 객체: ``spatial_ref_sys`` 는 x_extension 확장이
#    소유하며 app 스키마가 관리하지 않는다(search_path 때문에 schema=None 으로도
#    반사돼 이름으로 건다). shared DB의 infra owner가 설치한 ``postgis_topology``는
#    extension namespace와 무관하게 전용 ``topology`` schema에 객체를 만든다.
#    ``alembic_version`` 은 alembic 이 자동 제외한다.
_POSTGIS_TABLE_NAMES = frozenset({"spatial_ref_sys"})
_POSTGIS_OWNED_TABLES = frozenset(
    {
        ("topology", "layer"),
        ("topology", "topology"),
    }
)

_MAPPED_POSTGIS_OWNED_TABLES = sorted(
    f"{table.schema}.{table.name}"
    for table in target_metadata.tables.values()
    if (table.schema, table.name) in _POSTGIS_OWNED_TABLES
)
if _MAPPED_POSTGIS_OWNED_TABLES:
    raise RuntimeError(
        "application metadata maps PostGIS-owned tables: "
        + ", ".join(_MAPPED_POSTGIS_OWNED_TABLES)
    )

# 2) ORM 모델이 아직 없는 app-owned table (raw-SQL migration 으로만 생성).
#    weather/price 는 T-VN-17/38 이, ops-live/log/key 계열은 별도 wave 가 모델을
#    도입할 때 공용 ledger에서 제거한다. 그때까지 명시 제외한다.

# 모델을 추가한 뒤 위 제외 목록을 지우지 않으면 새 metadata drift를 영구히
# 숨길 수 있다. Alembic이 시작될 때 즉시 실패시켜 exclusion의 수명을 제한한다.
_STALE_UNMAPPED_APP_TABLES = _UNMAPPED_APP_TABLES.intersection(
    (table.schema, table.name) for table in target_metadata.tables.values()
)
if _STALE_UNMAPPED_APP_TABLES:
    stale_names = ", ".join(
        f"{schema}.{table}" for schema, table in sorted(_STALE_UNMAPPED_APP_TABLES)
    )
    msg = (
        "alembic unmapped-table exclusions now have SQLAlchemy mappings; "
        f"remove the stale exclusions: {stale_names}"
    )
    raise RuntimeError(msg)

# 3) alembic autogenerate 가 round-trip 하지 못하는 partial/expression index.
#    WHERE 절·JSONB expression 의 reflected 표현을 metadata 표현과 byte-identical 로
#    맞추지 못한다. 이름으로 제외하되, 삭제·정의 변경 미탐지 공백은
#    ``test_alembic_uncompared_indexes_keep_exact_semantics``가 UNIQUE 여부·키 순서·
#    predicate까지 PostgreSQL catalog로 고정해 메운다.


def _object_schema(object_: object) -> str | None:
    schema = getattr(object_, "schema", None)
    if isinstance(schema, str):
        return schema
    table = getattr(object_, "table", None)
    table_schema = getattr(table, "schema", None)
    return table_schema if isinstance(table_schema, str) else None


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001 — alembic callback signature.
    compare_to: object | None,
) -> bool:
    """비-app 객체와 미모델 app table/expression index 를 비교에서 제외한다."""

    schema = _object_schema(object_) or _object_schema(compare_to)
    if type_ == "table":
        # M01 ORM foundation은 0226 전까지 metadata에만 있다. 정확히
        # metadata-only add_table 후보만 숨긴다. 같은 이름의 live table은
        # compare_to가 있으므로 정상 비교되어 부분/불완전 DDL drift가 드러난다.
        if (
            not reflected
            and compare_to is None
            and (schema, name) in _PENDING_MIGRATION_TABLES
        ):
            return False
        return (
            name not in _POSTGIS_TABLE_NAMES
            and not (reflected and (schema, name) in _POSTGIS_OWNED_TABLES)
            and (schema, name) not in _UNMAPPED_APP_TABLES
        )
    if type_ == "index":
        return (schema, name) not in _UNCOMPARED_INDEXES
    return True


def run_migrations_offline() -> None:
    """offline mode — SQL 출력만 (실 DB connect 안 함)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # ⚠️ configure() 호출 시점에 connection이 트랜잭션 밖이어야 한다.
    # Alembic 1.18은 configure() 시 connection.in_transaction()을 보고
    # ``_in_external_transaction`` 을 판정하는데, True면 begin_transaction()이
    # nullcontext로 단락되어 **commit을 하지 않는다** (migration.py L156-161,
    # L416-417). 즉 search_path SET 등 어떤 execute()도 configure() 이전에
    # 하면 SQLAlchemy 2.0 autobegin으로 트랜잭션이 열려 → migration이 적용은
    # 되지만 connection close 시 rollback → 빈 DB. (Alembic ≤1.17에선 무증상.)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # 비교 시 server_default / type / nullable / ... 변경 모두 감지.
        compare_type=True,
        compare_server_default=True,
        # 비-app·미모델 객체 제외 (ADR-075 D-12-2, T-VN-19 alembic check gate).
        include_object=_include_object,
    )
    with context.begin_transaction():
        use_schema_owner_role = os.environ.get(_USE_SCHEMA_OWNER_ROLE_ENV, "false")
        if use_schema_owner_role not in {"true", "false"}:
            raise RuntimeError(
                f"{_USE_SCHEMA_OWNER_ROLE_ENV} must be exactly true or false"
            )
        if use_schema_owner_role == "true":
            # Bootstrap가 `ktm_feature_migrator`에게 이 NOLOGIN group으로의 SET
            # 권한만 부여한다. Alembic의 concurrent-index autocommit block은
            # transaction-local role을 reset하므로 dedicated migration connection
            # 수명 동안의 session role을 쓴다. connection close 시 reset되며 runtime은
            # 이 group membership을 절대 얻지 않는다.
            connection.execute(text("SET ROLE ktm_feature_schema_owner"))
        # 0201+ descendant의 downgrade가 일부 commit된 뒤 0200에서 멈추지 않도록
        # destination 전체를 migration step 실행 전에 판정한다.
        _guard_forward_only_target()
        # ADR-008 — search_path를 Alembic이 소유한 트랜잭션 **안에서** 설정.
        # 0002의 ``coord_5179`` STORED 생성 컬럼이 ``x_extension`` 의 PostGIS
        # ``ST_Transform`` 을 참조하므로 DDL 실행 전 search_path 필요.
        connection.execute(text("SET search_path = public, x_extension"))
        context.run_migrations()


async def run_async_migrations() -> None:
    """async mode — `AsyncEngine`으로 마이그레이션 실행.

    ``config.get_section``은 alembic.ini 원본 section을 반환하므로 위에서
    ``set_main_option``으로 갱신한 sqlalchemy.url이 빠질 수 있다. 명시적으로
    section dict에 박아 보장.
    """
    section = dict(config.get_section(config.config_ini_section, {}) or {})
    section["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """online mode — 실 DB connect (async)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
