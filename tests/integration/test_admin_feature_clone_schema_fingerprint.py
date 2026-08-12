"""clone checkpoint schema fingerprint의 pg_restore 정규화 회귀."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


# 이 모듈의 async 실행 주체는 anyio가 아니라 pytest-asyncio다.
# pyproject의 `asyncio_mode = "auto"` + `asyncio_default_*_loop_scope = "session"`이
# session-scope engine fixture와 function-scope async test에 같은 event loop을 물린다.
# 여기에 `pytest.mark.anyio`를 얹으면 anyio pytest plugin이 session-scope fixture까지
# 자기 wrapper로 감싸면서 module-scope `anyio_backend`를 요구해 setup 단계에서
# ScopeMismatch로 죽는다(테스트 본문과 무관한 배선 사고).
# 같은 디렉터리의 다른 통합 모듈과 동일하게 `integration` 마커만 달아
# testcontainers 게이트(`-m integration`) 선택 대상으로 남긴다.
pytestmark = pytest.mark.integration


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
    migrated_engine: AsyncEngine,
) -> None:
    """동등한 restore schema의 raw ordinal 차이는 fingerprint 차이가 아니다.

    ``pg_engine``이 아니라 ``migrated_engine``을 쓴다. 둘은 **같은 컨테이너 DB**를
    가리키므로 이 테스트가 보는 catalog는 어느 쪽이든 같지만, 소유권은 같지 않다:
    ``pg_engine``은 4개 app schema를 컨테이너 superuser 자격으로
    ``CREATE SCHEMA IF NOT EXISTS``하고, ``migrated_engine``은 배포와 같은 bootstrap
    으로 ``AUTHORIZATION ktm_feature_schema_owner``를 걸어 만든다(ADR-090). 세션에서
    **먼저 만들어진 쪽이 schema owner를 확정**하고 뒤의 ``IF NOT EXISTS``는 no-op이
    되므로, ``pg_engine``이 먼저 서면 이후 restricted migrator(``ktm_feature_migrator``
    → ``SET ROLE ktm_feature_schema_owner``)의 ``alembic upgrade``가
    ``permission denied for schema feature``로 죽는다. 이 모듈은 알파벳순으로
    tests/integration의 **첫 파일**이라 그 순서를 직접 결정한다 — 마이그레이션된
    엔진을 요구해 배포 경로가 먼저 서도록 못박는다.
    """
    names = (
        "clone_digest_child_clean",
        "clone_digest_child_gap",
        "clone_digest_parent_clean",
        "clone_digest_parent_gap",
    )
    async with migrated_engine.begin() as connection:
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
