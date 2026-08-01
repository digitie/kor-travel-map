"""0075 cache target outbox migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.models import (
    PoiCacheTargetReconciliationRequestRow,
    PoiCacheTargetRestoreFenceRow,
)

pytestmark = pytest.mark.integration

_PRE_REVISION = "0074_curation_item_rekey_cascade"
_TARGET_REVISION = "0075_cache_target_outbox"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_0075_phase_schema_and_downgrade(pg_container: Any) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"cache_target_0075_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            phase_column = await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ops' "
                    "AND table_name = 'poi_cache_target_reconciliation_requests' "
                    "AND column_name = 'phase_version'"
                )
            )
            status_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_reconciliation_requests'::regclass "
                    "AND conname = "
                    "'ck_cache_target_reconciliation_requests_status'"
                )
            )
            lifecycle_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_reconciliation_requests'::regclass "
                    "AND conname = "
                    "'ck_cache_target_reconciliation_requests_lifecycle'"
                )
            )
            delivery_status_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_outbox_deliveries'::regclass "
                    "AND pg_get_constraintdef(oid) LIKE '%pending%' "
                    "AND pg_get_constraintdef(oid) LIKE '%superseded%'"
                )
            )
            superseded_constraint = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_outbox_deliveries'::regclass "
                    "AND pg_get_constraintdef(oid) LIKE '%superseded_at%'"
                )
            )
            superseded_count_column = await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ops' "
                    "AND table_name = 'poi_cache_target_restore_fences' "
                    "AND column_name = 'superseded_delivery_count'"
                )
            )
            fence_receipt_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'ops' "
                            "AND table_name = 'poi_cache_target_restore_fences' "
                            "AND column_name IN ("
                            "'invalidated_claim_count',"
                            "'superseded_reconciliation_count',"
                            "'superseded_reconciliation_request_id')"
                        )
                    )
                ).scalars()
            )
            active_reconciliation_index = await connection.scalar(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'ops' "
                    "AND tablename = 'poi_cache_target_reconciliation_requests' "
                    "AND indexname = "
                    "'uq_cache_target_reconciliation_requests_active_stream'"
                )
            )
            stream_request_unique = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_reconciliation_requests'::regclass "
                    "AND conname = "
                    "'uq_cache_target_reconciliation_requests_stream_request'"
                )
            )
            stream_scoped_fence_fk = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = "
                    "'ops.poi_cache_target_restore_fences'::regclass "
                    "AND conname = "
                    "'fk_cache_target_restore_fences_superseded_reconciliation'"
                )
            )
            snapshot_item_table = await connection.scalar(
                text("SELECT to_regclass('ops.poi_cache_target_snapshot_items')")
            )
            append_only_function = await connection.scalar(
                text("SELECT to_regprocedure('ops.reject_cache_target_history_mutation()')")
            )
            snapshot_update_trigger = await connection.scalar(
                text(
                    "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = 'ops.poi_cache_target_snapshots'::regclass "
                    "AND tgname = 'trg_poi_cache_target_snapshots_append_only'"
                )
            )
            snapshot_item_update_trigger = await connection.scalar(
                text(
                    "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = "
                    "'ops.poi_cache_target_snapshot_items'::regclass "
                    "AND tgname = "
                    "'trg_poi_cache_target_snapshot_items_append_only'"
                )
            )
        assert revision == _TARGET_REVISION
        assert phase_column == "phase_version"
        assert status_constraint is not None
        assert "preparing" in status_constraint
        assert "running" in status_constraint
        assert "superseded" in status_constraint
        assert lifecycle_constraint is not None
        assert "snapshot_id IS NULL" in lifecycle_constraint
        assert "snapshot_id IS NOT NULL" in lifecycle_constraint
        assert "restore_fenced" in lifecycle_constraint
        assert delivery_status_constraint is not None
        assert "superseded" in delivery_status_constraint
        assert superseded_constraint is not None
        assert "superseded_at" in superseded_constraint
        assert superseded_count_column == "superseded_delivery_count"
        assert fence_receipt_columns == {
            "invalidated_claim_count",
            "superseded_reconciliation_count",
            "superseded_reconciliation_request_id",
        }
        assert (
            active_reconciliation_index
            == "uq_cache_target_reconciliation_requests_active_stream"
        )
        assert stream_request_unique == "UNIQUE (external_system, request_id)"
        assert stream_scoped_fence_fk == (
            "FOREIGN KEY (external_system, superseded_reconciliation_request_id) "
            "REFERENCES ops.poi_cache_target_reconciliation_requests"
            "(external_system, request_id) ON DELETE RESTRICT"
        )
        assert str(snapshot_item_table) == "ops.poi_cache_target_snapshot_items"
        assert str(append_only_function) == "ops.reject_cache_target_history_mutation()"
        assert "BEFORE UPDATE" in str(snapshot_update_trigger)
        assert "DELETE" not in str(snapshot_update_trigger)
        assert "BEFORE UPDATE" in str(snapshot_item_update_trigger)
        assert "DELETE" not in str(snapshot_item_update_trigger)

        reconciliation_constraints = {
            constraint.name: constraint
            for constraint in PoiCacheTargetReconciliationRequestRow.__table__.constraints
        }
        orm_unique = reconciliation_constraints[
            "uq_cache_target_reconciliation_requests_stream_request"
        ]
        assert isinstance(orm_unique, UniqueConstraint)
        assert [column.name for column in orm_unique.columns] == [
            "external_system",
            "request_id",
        ]
        fence_constraints = {
            constraint.name: constraint
            for constraint in PoiCacheTargetRestoreFenceRow.__table__.constraints
        }
        orm_fence_fk = fence_constraints[
            "fk_cache_target_restore_fences_superseded_reconciliation"
        ]
        assert isinstance(orm_fence_fk, ForeignKeyConstraint)
        assert [column.name for column in orm_fence_fk.columns] == [
            "external_system",
            "superseded_reconciliation_request_id",
        ]
        assert [element.target_fullname for element in orm_fence_fk.elements] == [
            "ops.poi_cache_target_reconciliation_requests.external_system",
            "ops.poi_cache_target_reconciliation_requests.request_id",
        ]
        assert orm_fence_fk.ondelete == "RESTRICT"

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            request_table = await connection.scalar(
                text("SELECT to_regclass('ops.poi_cache_target_reconciliation_requests')")
            )
            append_only_function = await connection.scalar(
                text("SELECT to_regprocedure('ops.reject_cache_target_history_mutation()')")
            )
            source_rule_function = await connection.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'feature.issue_curation_source_rule_decision()')"
                )
            )
            source_rule_trigger = await connection.scalar(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'feature.curation_items'::regclass "
                    "AND tgname = 'trg_curation_items_source_rule_decision' "
                    "AND NOT tgisinternal"
                )
            )
            rekey_function = await connection.scalar(
                text(
                    "SELECT to_regprocedure("
                    "'feature.reject_curation_history_mutation()')"
                )
            )
            cascaded_fk_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE connamespace = 'feature'::regnamespace "
                    "AND contype = 'f' AND confupdtype = 'c' "
                    "AND conname IN ("
                    "'fk_curation_import_rows_item',"
                    "'fk_curation_link_decisions_item',"
                    "'fk_curation_link_decisions_import_row',"
                    "'fk_curation_link_decisions_supersedes')"
                )
            )
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert request_table is None
        assert append_only_function is None
        assert (
            str(source_rule_function)
            == "feature.issue_curation_source_rule_decision()"
        )
        assert source_rule_trigger == "trg_curation_items_source_rule_decision"
        assert str(rekey_function) == "feature.reject_curation_history_mutation()"
        assert cascaded_fk_count == 4
        assert revision == _PRE_REVISION
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
