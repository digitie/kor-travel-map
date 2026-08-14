"""0046 notice lifecycle scope/lineage 상태 migration 검증."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_notice_snapshot_state_upgrade_and_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"notice_snapshot_migration_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, "0045_curation_collections")
        async with target_engine.begin() as connection:
            tables_before = (
                await connection.execute(
                    text(
                        "SELECT to_regclass('provider_sync.notice_lifecycle_scopes'), "
                        "to_regclass('provider_sync.notice_lineage_states')"
                    )
                )
            ).one()
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_entities (
                        source_entity_key, provider, dataset_key,
                        source_entity_type, source_entity_id,
                        first_seen_at, last_seen_at
                    ) VALUES (
                        'se_notice_lifecycle_migration', 'migration-provider',
                        'migration-dataset', 'notice', 'migration-entity',
                        now(), now()
                    )
                    """
                )
            )
        assert tables_before == (None, None)

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, "0046_notice_snapshot_state")
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            columns = (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'provider_sync'
                          AND table_name IN (
                              'notice_lifecycle_scopes',
                              'notice_lineage_states'
                          )
                        """
                    )
                )
            ).all()
            constraints = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT cls.relname AS table_name,
                                   constraint_row.conname,
                                   constraint_row.contype::text AS contype,
                                   constraint_row.confdeltype::text AS confdeltype,
                                   pg_get_constraintdef(
                                       constraint_row.oid, true
                                   ) AS definition
                            FROM pg_constraint AS constraint_row
                            JOIN pg_class AS cls
                              ON cls.oid = constraint_row.conrelid
                            JOIN pg_namespace AS namespace
                              ON namespace.oid = cls.relnamespace
                            WHERE namespace.nspname = 'provider_sync'
                              AND cls.relname IN (
                                  'notice_lifecycle_scopes',
                                  'notice_lineage_states'
                              )
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )

            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.notice_lifecycle_scopes (
                        provider, dataset_key, source_entity_type,
                        mode, applied_at, state_fingerprint
                    ) VALUES (
                        'migration-provider', 'migration-dataset', 'notice',
                        'snapshot', '2026-07-14T00:00:00+09:00',
                        'snapshot:migration-fingerprint'
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.notice_lineage_states (
                        provider, dataset_key, source_entity_type,
                        lineage_key, present, changed_at, valid_until
                    ) VALUES (
                        'migration-provider', 'migration-dataset', 'notice',
                        'migration-lineage', true,
                        '2026-07-14T00:00:00+09:00',
                        '2026-07-15T00:00:00+09:00'
                    )
                    """
                )
            )
            stored = (
                await connection.execute(
                    text(
                        """
                        SELECT scope.mode, scope.state_fingerprint,
                               lineage.lineage_key, lineage.present,
                               lineage.valid_until
                        FROM provider_sync.notice_lifecycle_scopes AS scope
                        JOIN provider_sync.notice_lineage_states AS lineage
                          USING (provider, dataset_key, source_entity_type)
                        WHERE scope.provider = 'migration-provider'
                          AND scope.dataset_key = 'migration-dataset'
                          AND scope.source_entity_type = 'notice'
                        """
                    )
                )
            ).one()

        assert set(columns) == {
            ("notice_lifecycle_scopes", "provider", "text", "NO"),
            ("notice_lifecycle_scopes", "dataset_key", "text", "NO"),
            ("notice_lifecycle_scopes", "source_entity_type", "text", "NO"),
            ("notice_lifecycle_scopes", "mode", "text", "NO"),
            (
                "notice_lifecycle_scopes",
                "applied_at",
                "timestamp with time zone",
                "NO",
            ),
            ("notice_lifecycle_scopes", "state_fingerprint", "text", "NO"),
            ("notice_lineage_states", "provider", "text", "NO"),
            ("notice_lineage_states", "dataset_key", "text", "NO"),
            ("notice_lineage_states", "source_entity_type", "text", "NO"),
            ("notice_lineage_states", "lineage_key", "text", "NO"),
            ("notice_lineage_states", "present", "boolean", "NO"),
            (
                "notice_lineage_states",
                "changed_at",
                "timestamp with time zone",
                "NO",
            ),
            (
                "notice_lineage_states",
                "valid_until",
                "timestamp with time zone",
                "YES",
            ),
        }
        constraint_map = {
            (row["table_name"], row["conname"]): row for row in constraints
        }
        scope_pk = constraint_map[
            ("notice_lifecycle_scopes", "pk_notice_lifecycle_scopes")
        ]
        assert scope_pk["contype"] == "p"
        assert scope_pk["definition"] == (
            "PRIMARY KEY (provider, dataset_key, source_entity_type)"
        )
        scope_mode = constraint_map[
            ("notice_lifecycle_scopes", "ck_notice_lifecycle_scopes_mode")
        ]
        assert scope_mode["contype"] == "c"
        assert "mode" in scope_mode["definition"]
        assert "snapshot" in scope_mode["definition"]
        assert "event" in scope_mode["definition"]

        lineage_pk = constraint_map[
            ("notice_lineage_states", "pk_notice_lineage_states")
        ]
        assert lineage_pk["contype"] == "p"
        assert lineage_pk["definition"] == (
            "PRIMARY KEY (provider, dataset_key, source_entity_type, lineage_key)"
        )
        lineage_fk = constraint_map[
            ("notice_lineage_states", "fk_notice_lineage_states_scope")
        ]
        assert lineage_fk["contype"] == "f"
        assert lineage_fk["confdeltype"] == "c"
        assert lineage_fk["definition"].startswith(
            "FOREIGN KEY (provider, dataset_key, source_entity_type) "
            "REFERENCES provider_sync.notice_lifecycle_scopes"
        )
        assert stored == (
            "snapshot",
            "snapshot:migration-fingerprint",
            "migration-lineage",
            True,
            datetime.fromisoformat("2026-07-15T00:00:00+09:00"),
        )

        await target_engine.dispose()
        with pytest.raises(DBAPIError, match="0046 downgrade refused"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                "0045_curation_collections",
                downgrade=True,
            )

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM provider_sync.notice_lifecycle_scopes")
            )
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            "0045_curation_collections",
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            tables_after = (
                await connection.execute(
                    text(
                        "SELECT to_regclass('provider_sync.notice_lifecycle_scopes'), "
                        "to_regclass('provider_sync.notice_lineage_states')"
                    )
                )
            ).one()
            source_entities = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM provider_sync.source_entities "
                        "WHERE source_entity_key = 'se_notice_lifecycle_migration'"
                    )
                )
            ).scalar_one()
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
        assert tables_after == (None, None)
        assert source_entities == 1
        assert revision == "0045_curation_collections"
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
