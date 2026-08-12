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

    ``migrated_engine``을 쓴다 — 이 fixture는 배포 경로로 올린 **전용 DB**를 준다.
    예전에는 그것이 컨테이너 기본 DB를 ``pg_engine``과 공유해서, 세션에서 먼저 선
    쪽이 app schema owner를 확정하는 순서 결합이 있었다. 그때는 이 모듈이 알파벳순
    첫 파일이라는 사실에 기대 배포 경로를 먼저 세웠는데, 파일 하나가 추가되거나
    이름이 바뀌면 조용히 깨지는 장치였다. 지금은 DB가 분리돼 순서가 무의미하다.
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
