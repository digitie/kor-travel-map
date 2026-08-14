"""0068 integrity ledger 최신 관측 시각 migration 회귀 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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

_PRE_REVISION = "0067_integrity_dedupe_key"
_TARGET_REVISION = "0068_integrity_last_seen"


def _run_alembic(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


async def test_integrity_last_seen_upgrade_preserves_free_form_payload(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"integrity_last_seen_{uuid4().hex}"
    target_dsn = (
        make_url(admin_dsn)
        .set(database=database)
        .render_as_string(hide_password=False)
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
                    INSERT INTO ops.data_integrity_violations (
                        issue_id, violation_type, severity, message,
                        payload, detected_at
                    ) VALUES (
                        CAST(:issue_id AS uuid), 'manual_payload', 'warning',
                        :message, CAST(:payload AS jsonb),
                        CAST(:detected_at AS timestamptz)
                    )
                    """
                ),
                [
                    {
                        "issue_id": "68000000-0000-4000-8000-000000000001",
                        "message": "malformed",
                        "payload": (
                            '{"last_seen_at":"not-a-timestamp",'
                            '"marker":"malformed"}'
                        ),
                        "detected_at": datetime(2026, 7, 1, tzinfo=UTC),
                    },
                    {
                        "issue_id": "68000000-0000-4000-8000-000000000002",
                        "message": "null",
                        "payload": '{"last_seen_at":null,"marker":"null"}',
                        "detected_at": datetime(2026, 7, 2, tzinfo=UTC),
                    },
                    {
                        "issue_id": "68000000-0000-4000-8000-000000000003",
                        "message": "offset",
                        "payload": (
                            '{"last_seen_at":"2026-07-03T09:00:00+09:00",'
                            '"marker":"offset"}'
                        ),
                        "detected_at": datetime(2026, 7, 3, tzinfo=UTC),
                    },
                    ],
                )
            # 첫 autocommit 직후 runner가 중단된 상태를 재현한다. revision은 여전히
            # 0067이고 column/default 및 후보 index만 남아도 forward 재실행돼야 한다.
            await connection.execute(
                text(
                    """
                    ALTER TABLE ops.data_integrity_violations
                    ADD COLUMN last_seen_at timestamptz,
                    ALTER COLUMN last_seen_at SET DEFAULT now()
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE INDEX idx_violations_status_seen
                    ON ops.data_integrity_violations
                      (status, last_seen_at DESC, issue_id DESC)
                    """
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT message, payload, detected_at, last_seen_at
                        FROM ops.data_integrity_violations
                        ORDER BY issue_id
                        """
                    )
                )
            ).mappings().all()
            feature_fk_delete_action = (
                await connection.execute(
                    text(
                        """
                            SELECT confdeltype::text
                        FROM pg_constraint
                        WHERE conname =
                          'fk_data_integrity_violations_feature_id_features'
                        """
                    )
                )
            ).scalar_one()
            valid_indexes = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT index_class.relname
                            FROM pg_index AS index_row
                            JOIN pg_class AS index_class
                              ON index_class.oid = index_row.indexrelid
                            JOIN pg_class AS table_class
                              ON table_class.oid = index_row.indrelid
                            JOIN pg_namespace AS namespace
                              ON namespace.oid = table_class.relnamespace
                            WHERE namespace.nspname = 'ops'
                              AND table_class.relname =
                                'data_integrity_violations'
                              AND index_row.indisvalid
                            """
                        )
                    )
                ).scalars()
            )

        assert [row["message"] for row in rows] == ["malformed", "null", "offset"]
        assert all(row["last_seen_at"] == row["detected_at"] for row in rows)
        assert [row["payload"]["marker"] for row in rows] == [
            "malformed",
            "null",
            "offset",
        ]
        assert [row["payload"]["last_seen_at"] for row in rows] == [
            "not-a-timestamp",
            None,
            "2026-07-03T09:00:00+09:00",
        ]
        assert feature_fk_delete_action == "n"
        assert {
            "idx_violations_status_seen",
            "idx_violations_provider_status_seen",
            "idx_violations_feature_seen",
        } <= valid_indexes
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
