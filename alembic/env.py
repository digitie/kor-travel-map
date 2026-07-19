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

_FORWARD_ONLY_BOUNDARY = "0060_weather_integrity"


def _guard_forward_only_target() -> None:
    """Alembic의 실제 실행 계획이 0060을 내리면 첫 step 전에 거부한다."""
    migration_context = context.get_context()
    migration_fn = migration_context.opts.get("fn")
    if migration_fn is None:
        # ``current``처럼 migration plan이 없는 read-only command.
        return

    current_heads = migration_context.get_current_heads()
    planned_steps = tuple(migration_fn(current_heads, migration_context))
    crosses_boundary = any(
        step.is_downgrade
        and _FORWARD_ONLY_BOUNDARY in step.from_revisions_no_deps
        for step in planned_steps
    )
    if crosses_boundary:
        raise RuntimeError(
            "0060 is forward-only: restore the pre-cutover backup/PITR under a "
            "writer fence and roll back the writer image as one operation"
        )


# ``alembic check`` 정합 필터 (ADR-075 D-12-2, T-VN-19).
# ``include_schemas=True`` + ``compare_type`` 은 app schema 밖 객체와 아직 ORM
# 모델이 없는 app table까지 비교해 clean DB check 를 실패시킨다. 아래 3개 명시
# 목록만 비교에서 제외한다(blanket ignore 아님 — 이름을 전부 나열).
#
# 1) PostGIS/extension 소유 객체: ``spatial_ref_sys`` 는 x_extension 확장이
#    소유하며 app 스키마가 관리하지 않는다(search_path 때문에 schema=None 으로도
#    반사돼 이름으로 건다). ``alembic_version`` 은 alembic 이 자동 제외한다.
_POSTGIS_TABLE_NAMES = frozenset({"spatial_ref_sys"})

# 2) ORM 모델이 아직 없는 app-owned table (raw-SQL migration 으로만 생성).
#    weather/price 는 T-VN-17/38 이, ops-live/log/key 계열은 별도 wave 가 모델을
#    도입할 때 이 목록에서 제거한다. 그때까지 명시 제외한다.
_UNMAPPED_APP_TABLES = frozenset(
    {
        "feature_weather_values",
        "feature_price_values",
        "system_log",
        "api_call_log",
        "public_api_keys",
        "admin_auth_events",
        "ops_live_ticket_claims",
        "ops_live_topic_revisions",
    }
)

# 3) alembic autogenerate 가 round-trip 하지 못하는 index. partial/expression
#    index 는 WHERE 절·JSONB expression 의 reflected 표현을 metadata 표현과
#    byte-identical 로 맞추지 못하고, ``uq_curated_features_theme_feature_active``
#    는 ``UUID(as_uuid=False)`` 컬럼을 reflection 이 ``UUID()`` 로 되읽어
#    compare_type 위양성이 난다(둘 다 실제 DB 타입은 uuid/text 로 동일). 이름으로만
#    제외하며, exclusion 이 여는 삭제-미탐지 공백은 존재 단언으로 메운다:
#    ``idx_features_dedup_refresh_keyset`` 는
#    ``tests/integration/test_t212d_perf_explain.py`` 의 EXPLAIN 이, 나머지 4개는
#    ``tests/integration/test_alembic_upgrade.py::test_alembic_excluded_indexes_still_exist``
#    가 pg_indexes 로 존재를 지킨다.
_UNCOMPARED_INDEXES = frozenset(
    {
        "idx_features_dedup_refresh_keyset",
        "idx_features_yt_channel_id",
        "idx_features_yt_playlist_id",
        "idx_source_records_kma_alert_history",
        "uq_curated_features_theme_feature_active",
    }
)


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001 — alembic callback signature.
    compare_to: object,
) -> bool:
    """비-app 객체와 미모델 app table/expression index 를 비교에서 제외한다."""

    if type_ == "table":
        return name not in _POSTGIS_TABLE_NAMES and name not in _UNMAPPED_APP_TABLES
    if type_ == "index":
        return name not in _UNCOMPARED_INDEXES
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
        # 0061+ descendant의 downgrade가 일부 commit된 뒤 0060에서 멈추지 않도록
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
