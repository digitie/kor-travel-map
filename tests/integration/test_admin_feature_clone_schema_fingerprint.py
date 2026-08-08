"""clone checkpoint schema fingerprint의 pg_restore 정규화 회귀."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


pytestmark = pytest.mark.anyio


async def _constraint_key_names(
    connection: AsyncConnection, constraint_name: str
) -> tuple[str, str]:
    """runner와 같은 key column-name 정규화를 실행한다."""
    row = (
        await connection.execute(
            text(
                """
                SELECT
                  COALESCE(
                    (
                      SELECT string_agg(
                        key_attribute.attname,
                        ',' ORDER BY array_position(
                          constraint_row.conkey,
                          key_attribute.attnum
                        )
                      )
                      FROM pg_catalog.pg_attribute AS key_attribute
                      WHERE key_attribute.attrelid = constraint_row.conrelid
                        AND key_attribute.attnum = ANY(constraint_row.conkey)
                    ),
                    ''
                  ) AS key_columns,
                  COALESCE(
                    (
                      SELECT string_agg(
                        referenced_attribute.attname,
                        ',' ORDER BY array_position(
                          constraint_row.confkey,
                          referenced_attribute.attnum
                        )
                      )
                      FROM pg_catalog.pg_attribute AS referenced_attribute
                      WHERE referenced_attribute.attrelid = constraint_row.confrelid
                        AND referenced_attribute.attnum = ANY(constraint_row.confkey)
                    ),
                    ''
                  ) AS referenced_columns
                FROM pg_catalog.pg_constraint AS constraint_row
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = constraint_row.connamespace
                WHERE namespace.nspname = 'provider_sync'
                  AND constraint_row.conname = :constraint_name
                """
            ),
            {"constraint_name": constraint_name},
        )
    ).one()
    return str(row.key_columns), str(row.referenced_columns)


async def _dense_column_order(
    connection: AsyncConnection, relation_name: str
) -> str:
    """dropped attnum gap은 무시하고 active column order는 보존한다."""
    return str(
        (
            await connection.execute(
                text(
                    """
                    SELECT string_agg(
                      dense_position::text || ':' || attname,
                      ',' ORDER BY dense_position
                    )
                    FROM (
                      SELECT
                        row_number() OVER (
                          PARTITION BY attribute.attrelid
                          ORDER BY attribute.attnum
                        ) AS dense_position,
                        attribute.attname
                      FROM pg_catalog.pg_attribute AS attribute
                      JOIN pg_catalog.pg_class AS relation
                        ON relation.oid = attribute.attrelid
                      JOIN pg_catalog.pg_namespace AS namespace
                        ON namespace.oid = relation.relnamespace
                      WHERE namespace.nspname = 'provider_sync'
                        AND relation.relname = :relation_name
                        AND attribute.attnum > 0
                        AND NOT attribute.attisdropped
                    ) AS active_columns
                    """
                ),
                {"relation_name": relation_name},
            )
        ).scalar_one()
    )


async def _raw_constraint_key(
    connection: AsyncConnection, constraint_name: str
) -> str:
    return str(
        (
            await connection.execute(
                text(
                    """
                    SELECT constraint_row.conkey::text || ':' ||
                      COALESCE(constraint_row.confkey::text, '')
                    FROM pg_catalog.pg_constraint AS constraint_row
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = constraint_row.connamespace
                    WHERE namespace.nspname = 'provider_sync'
                      AND constraint_row.conname = :constraint_name
                    """
                ),
                {"constraint_name": constraint_name},
            )
        ).scalar_one()
    )


async def test_checkpoint_fingerprint_normalizes_dropped_attnum_gaps(
    pg_engine: AsyncEngine,
) -> None:
    """동등한 restore schema의 raw ordinal 차이는 fingerprint 차이가 아니다."""
    names = (
        "clone_digest_child_clean",
        "clone_digest_child_gap",
        "clone_digest_parent_clean",
        "clone_digest_parent_gap",
    )
    async with pg_engine.begin() as connection:
        try:
            statements = (
                """
                    CREATE TABLE provider_sync.clone_digest_parent_gap (
                      id bigint NOT NULL,
                      obsolete text,
                      code text NOT NULL,
                      CONSTRAINT clone_digest_parent_gap_code_key UNIQUE (code)
                    )
                """,
                """
                    ALTER TABLE provider_sync.clone_digest_parent_gap
                      DROP COLUMN obsolete
                """,
                """
                    CREATE TABLE provider_sync.clone_digest_parent_clean (
                      id bigint NOT NULL,
                      code text NOT NULL,
                      CONSTRAINT clone_digest_parent_clean_code_key UNIQUE (code)
                    )
                """,
                """
                    CREATE TABLE provider_sync.clone_digest_child_gap (
                      id bigint NOT NULL,
                      obsolete text,
                      parent_code text NOT NULL
                    )
                """,
                """
                    ALTER TABLE provider_sync.clone_digest_child_gap
                      DROP COLUMN obsolete
                """,
                """
                    ALTER TABLE provider_sync.clone_digest_child_gap
                      ADD CONSTRAINT clone_digest_child_gap_parent_fk
                      FOREIGN KEY (parent_code)
                      REFERENCES provider_sync.clone_digest_parent_gap (code)
                """,
                """
                    CREATE TABLE provider_sync.clone_digest_child_clean (
                      id bigint NOT NULL,
                      parent_code text NOT NULL,
                      CONSTRAINT clone_digest_child_clean_parent_fk
                      FOREIGN KEY (parent_code)
                      REFERENCES provider_sync.clone_digest_parent_clean (code)
                    )
                """,
            )
            for statement in statements:
                await connection.execute(text(statement))

            assert await _dense_column_order(
                connection, "clone_digest_parent_gap"
            ) == await _dense_column_order(connection, "clone_digest_parent_clean")
            assert await _raw_constraint_key(
                connection, "clone_digest_parent_gap_code_key"
            ) != await _raw_constraint_key(
                connection, "clone_digest_parent_clean_code_key"
            )
            assert await _constraint_key_names(
                connection, "clone_digest_parent_gap_code_key"
            ) == await _constraint_key_names(
                connection, "clone_digest_parent_clean_code_key"
            )
            assert await _raw_constraint_key(
                connection, "clone_digest_child_gap_parent_fk"
            ) != await _raw_constraint_key(
                connection, "clone_digest_child_clean_parent_fk"
            )
            assert await _constraint_key_names(
                connection, "clone_digest_child_gap_parent_fk"
            ) == await _constraint_key_names(
                connection, "clone_digest_child_clean_parent_fk"
            )
        finally:
            for name in names:
                await connection.execute(
                    text(f"DROP TABLE IF EXISTS provider_sync.{name} CASCADE")
                )
