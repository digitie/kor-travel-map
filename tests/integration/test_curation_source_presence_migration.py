"""0065 curation source presence schema migration 회귀."""

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

_PRE_REVISION = "0064_price_series_identity"
_TARGET_REVISION = "0065_curation_source_presence"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _schema_state(engine: Any) -> tuple[tuple[Any, ...] | None, dict[str, str]]:
    async with engine.connect() as connection:
        column = (
            await connection.execute(
                text(
                    "SELECT is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'feature' "
                    "AND table_name = 'curation_items' "
                    "AND column_name = 'source_present'"
                )
            )
        ).one_or_none()
        indexes = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'feature' "
                "AND tablename = 'curation_items'"
            )
        )
    return column, {str(name): str(definition) for name, definition in indexes}


async def test_source_presence_upgrade_downgrade_forward_recovery(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_source_presence_{uuid4().hex}"
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
        before_column, before_indexes = await _schema_state(target_engine)
        assert before_column is None
        assert "source_present" not in (
            before_indexes["idx_curation_items_collection_status_order"]
        )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        upgraded_column, upgraded_indexes = await _schema_state(target_engine)
        assert upgraded_column == ("NO", "true")
        assert "collection_id, source_present, status, sort_order" in (
            upgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "feature_id, source_present, status, collection_id" in (
            upgraded_indexes["idx_curation_items_feature_status_collection"]
        )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        downgraded_column, downgraded_indexes = await _schema_state(target_engine)
        assert downgraded_column is None
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_feature_status_collection"]
        )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        recovered_column, recovered_indexes = await _schema_state(target_engine)
        assert recovered_column == ("NO", "true")
        assert "source_present" in (
            recovered_indexes["idx_curation_items_collection_status_order"]
        )
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
