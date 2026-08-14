"""0064 price full series identity index migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0063_pipeline_root_id"
_TARGET_REVISION = "0064_price_series_identity"
_OLD_INDEX = "idx_price_values_feature_product_observed"
_HISTORY_INDEX = "idx_price_values_feature_observed_identity"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — `alembic/legacy_versions/README.md`. `versions/`와 함께 담으면 revision이 중복된다.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _price_index_defs(engine: Any) -> dict[str, str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'feature' "
                "AND tablename = 'feature_price_values'"
            )
        )
    return {str(name): str(definition) for name, definition in rows}


async def _alembic_revision(engine: Any) -> str:
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision is not None
    return str(revision)


async def test_price_series_index_upgrade_downgrade_forward_recovery(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"price_series_identity_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        before = await _price_index_defs(target_engine)
        assert _OLD_INDEX in before
        assert _HISTORY_INDEX not in before

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        upgraded = await _price_index_defs(target_engine)
        assert _OLD_INDEX not in upgraded
        assert (
            "feature_id, observed_at DESC, provider, price_domain, product_key"
            in (upgraded[_HISTORY_INDEX])
        )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        downgraded = await _price_index_defs(target_engine)
        assert _HISTORY_INDEX not in downgraded
        assert "feature_id, price_domain, product_key, observed_at DESC" in (downgraded[_OLD_INDEX])

        # 중단된 선행 시도가 같은 이름을 남겨도 upgrade가 제거하고 정본으로 복구한다.
        async with target_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(
                    # key는 같아도 INCLUDE가 붙은 same-name index는 정본이 아니다.
                    "CREATE INDEX idx_price_values_feature_observed_identity "
                    "ON feature.feature_price_values "
                    "(feature_id, observed_at DESC, provider, price_domain, product_key) "
                    "INCLUDE (value_number)"
                )
            )
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        recovered = await _price_index_defs(target_engine)
        assert _OLD_INDEX not in recovered
        assert (
            "feature_id, observed_at DESC, provider, price_domain, product_key"
            in (recovered[_HISTORY_INDEX])
        )

        # DDL은 끝났지만 Alembic stamp가 실패한 partial downgrade를 재실행한다.
        # 이미 유일한 유효 access path인 old index를 먼저 지우면 안 된다.
        async with target_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(
                    "CREATE INDEX idx_price_values_feature_product_observed "
                    "ON feature.feature_price_values "
                    "(feature_id, price_domain, product_key, observed_at DESC)"
                )
            )
            await autocommit.execute(
                text("DROP INDEX feature.idx_price_values_feature_observed_identity")
            )
        assert await _alembic_revision(target_engine) == _TARGET_REVISION
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        recovered_downgrade = await _price_index_defs(target_engine)
        assert _HISTORY_INDEX not in recovered_downgrade
        assert (
            "feature_id, price_domain, product_key, observed_at DESC"
            in (recovered_downgrade[_OLD_INDEX])
        )
        assert await _alembic_revision(target_engine) == _PRE_REVISION

        # 대칭인 partial upgrade도 canonical history index를 그대로 채택하고 stamp한다.
        async with target_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(
                    "CREATE INDEX idx_price_values_feature_observed_identity "
                    "ON feature.feature_price_values "
                    "(feature_id, observed_at DESC, provider, price_domain, product_key)"
                )
            )
            await autocommit.execute(
                text("DROP INDEX feature.idx_price_values_feature_product_observed")
            )
        assert await _alembic_revision(target_engine) == _PRE_REVISION
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        recovered_upgrade = await _price_index_defs(target_engine)
        assert _OLD_INDEX not in recovered_upgrade
        assert (
            "feature_id, observed_at DESC, provider, price_domain, product_key"
            in (recovered_upgrade[_HISTORY_INDEX])
        )
        assert await _alembic_revision(target_engine) == _TARGET_REVISION
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()
