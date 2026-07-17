"""0056 provider refresh policy BIGINT revision migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0055_ops_live_ticket_claims"
_TARGET_REVISION = "0056_provider_refresh_policy_revision"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_revision_backfill_default_constraint_and_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"provider_policy_revision_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.provider_refresh_policies (
                      provider, dataset_key, source_kind
                    ) VALUES ('legacy-provider', 'legacy-dataset', 'manual')
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            column = (
                await connection.execute(
                    text(
                        """
                        SELECT data_type, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'provider_refresh_policies'
                          AND column_name = 'revision'
                        """
                    )
                )
            ).one()
            backfilled = (
                await connection.execute(
                    text(
                        """
                        SELECT revision
                        FROM ops.provider_refresh_policies
                        WHERE provider = 'legacy-provider'
                          AND dataset_key = 'legacy-dataset'
                        """
                    )
                )
            ).scalar_one()
            inserted = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO ops.provider_refresh_policies (
                          provider, dataset_key, source_kind
                        ) VALUES ('new-provider', 'new-dataset', 'manual')
                        RETURNING revision
                        """
                    )
                )
            ).scalar_one()
            constraint = (
                await connection.execute(
                    text(
                        """
                        SELECT pg_get_constraintdef(oid)
                        FROM pg_constraint
                        WHERE connamespace = 'ops'::regnamespace
                          AND conname = 'ck_provider_refresh_revision'
                        """
                    )
                )
            ).scalar_one()
            current_revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()

        assert column.data_type == "bigint"
        assert column.is_nullable == "NO"
        assert column.column_default == "1"
        assert backfilled == inserted == 1
        assert "revision > 0" in constraint
        assert current_revision == _TARGET_REVISION

        async with target_engine.begin() as connection:
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.provider_refresh_policies (
                              provider, dataset_key, source_kind, revision
                            ) VALUES ('bad-provider', 'bad-dataset', 'manual', 0)
                            """
                        )
                    )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision_column = (
                await connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'ops'
                          AND table_name = 'provider_refresh_policies'
                          AND column_name = 'revision'
                        """
                    )
                )
            ).one_or_none()
            surviving = (
                await connection.execute(
                    text("SELECT count(*) FROM ops.provider_refresh_policies")
                )
            ).scalar_one()
        assert revision_column is None
        assert surviving == 2
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
