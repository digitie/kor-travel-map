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
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from kortravelmap.infra.db import normalize_async_dsn
from kortravelmap.infra.models import metadata

if TYPE_CHECKING:
    pass

# Alembic Config — alembic.ini.
config = context.config

# Logging setup.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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
    )
    with context.begin_transaction():
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
