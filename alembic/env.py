"""Alembic env.py — async-compatible, SecretStr DSN injection (ADR-007).

DSN은 `KrtourMapSettings.pg_dsn` (`KRTOUR_MAP_PG_DSN` env var)에서 읽는다.
asyncpg driver로 정규화 후 `AsyncEngine`을 만들어 마이그레이션 실행.

``infra/models.py``의 ``metadata``를 ``target_metadata``로 사용 — autogenerate
지원 (현 PR#28부터). search_path는 ``public, x_extension`` (ADR-008).

사용:
    KRTOUR_MAP_PG_DSN=postgresql://... alembic upgrade head
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from krtour.map.infra.db import normalize_async_dsn
from krtour.map.infra.models import metadata
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    pass

# Alembic Config — alembic.ini.
config = context.config

# Logging setup.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DSN 주입 — env > alembic.ini placeholder.
settings = KrtourMapSettings()
config.set_main_option(
    "sqlalchemy.url",
    normalize_async_dsn(settings.pg_dsn.get_secret_value()),
)

# autogenerate 대상 metadata.
target_metadata = metadata


def _set_search_path(connection: Connection) -> None:
    """ADR-008 — 모든 connection에 ``search_path = public, x_extension``."""
    connection.execute(text("SET search_path = public, x_extension"))


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
    _set_search_path(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # 비교 시 server_default / type / nullable / ... 변경 모두 감지.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """async mode — `AsyncEngine`으로 마이그레이션 실행."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
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
